"""Fenced validation and cleanup jobs. No AI executor is installed here."""
import asyncio
from contextlib import suppress
from datetime import datetime, timezone, timedelta
import hashlib
from io import BytesIO
from uuid import uuid5, NAMESPACE_URL
from PIL import Image
from sqlalchemy import select, update, or_
from backend.models import Album, Page, MediaAsset, Upload, Job, Task, Attempt
from backend.media.process import normalize_in_process
from backend.media.contracts import MediaValidationError
from backend.storage.local import storage_key, canonical_asset_keys
from backend.storage.factory import media_storage
from backend.storage.r2 import StorageUnavailable
from backend.storage.snapshot import input_file
from backend.telemetry import span, emit
from backend.uploads.service import touch
from backend.uploads.preprocessing import preprocessing_hints
from backend.albums.page_order import sort_date, finish_batch, bump_version
from backend.worker.jobs import claim_job, finish_job, enqueue_job


def now(): return datetime.now(timezone.utc)


def source_mime(path):
    with path.open('rb') as f: head=f.read(64)
    if head.startswith(b'\xff\xd8\xff'): return 'image/jpeg'
    if head.startswith(b'\x89PNG\r\n\x1a\n'): return 'image/png'
    if head[:4]==b'RIFF' and head[8:12]==b'WEBP': return 'image/webp'
    if head[4:8]==b'ftyp': return 'image/heic' if any(x in head for x in (b'heic',b'heix',b'hevc',b'hevx')) else 'image/heif'
    raise MediaValidationError('IMAGE_DECODE_FAILED')


class ValidationWorker:
    def __init__(self,sessions,settings,*,lease_seconds=90,heartbeat_seconds=15):
        if not 0<heartbeat_seconds<lease_seconds: raise ValueError('invalid heartbeat')
        self.sessions=sessions; self.settings=settings; self.store=media_storage(settings)
        self.lease_seconds=lease_seconds; self.heartbeat_seconds=heartbeat_seconds
        self._deleted_scan_after = None

    async def _heartbeat(self,claim):
        while True:
            await asyncio.sleep(self.heartbeat_seconds)
            async with self.sessions() as s,s.begin():
                stamp=now()
                result=await s.execute(update(Job).where(Job.id==claim.job_id,Job.status=='running',Job.fence_version==claim.fence_version,Job.lease_until>stamp).values(lease_until=stamp+timedelta(seconds=self.lease_seconds)))
                if not result.rowcount: return

    async def run_once(self):
        async with self.sessions() as s:
            claim=await claim_job(s,now(),self.lease_seconds,('validate_upload','cleanup_album','cleanup_asset'))
        if claim is None: return False
        heartbeat=asyncio.create_task(self._heartbeat(claim))
        work=asyncio.create_task(self._timed_handle(claim))
        try:
            done,_=await asyncio.wait((work,heartbeat),return_when=asyncio.FIRST_COMPLETED)
            if heartbeat in done:
                # Lost lease/heartbeat failure cancels and reaps the media child.
                work.cancel()
                with suppress(asyncio.CancelledError): await work
                if heartbeat.exception(): raise heartbeat.exception()
            else:
                await work
        except asyncio.CancelledError:
            work.cancel()
            with suppress(asyncio.CancelledError): await work
            raise
        except Exception:
            async with self.sessions() as s:
                await finish_job(s,claim,now(),'retry_wait')
            raise
        finally:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError): await heartbeat
        return True

    async def _timed_handle(self,claim):
        with span('validation.execute', job_id=claim.job_id, kind=claim.kind):
            await self.handle(claim)

    async def handle(self,claim):
        if claim.kind=='validate_upload': await self.validate_upload(claim)
        elif claim.kind=='cleanup_album': await self.cleanup_album(claim)
        elif claim.kind=='cleanup_asset': await self.cleanup_asset(claim)
        else: raise ValueError('unsupported job')

    async def _rows(self,s,claim):
        album_id=await s.scalar(select(Upload.album_id).where(Upload.id==claim.target_id))
        album=await s.scalar(select(Album).where(Album.id==album_id).with_for_update()) if album_id else None
        upload=await s.get(Upload,claim.target_id)
        page=await s.get(Page,upload.page_id) if upload else None
        asset=await s.get(MediaAsset,upload.asset_id) if upload else None
        job=await s.scalar(select(Job).where(Job.id==claim.job_id).with_for_update())
        valid=job is not None and job.status=='running' and job.fence_version==claim.fence_version and job.lease_until is not None and job.lease_until>now()
        active=(album is not None and album.deleted_at is None and album.status!='deleted' and page is not None and page.removed_at is None
                and asset is not None and asset.owner_id==album.owner_id and asset.album_id==album.id and asset.page_id==page.id
                and page.album_id==album.id and page.source_asset_id==asset.id and asset.role=='source'
                and asset.storage_key==storage_key(album.owner_id,album.id,page.id,'source')
                and asset.deleted_at is None and asset.status in {'pending','ready'} and upload.status=='validating')
        return album,upload,page,asset,job,valid,active

    async def validate_upload(self,claim):
        async with self.sessions() as s,s.begin():
            album,u,page,asset,job,valid,active=await self._rows(s,claim)
            if not valid: return
            if not active:
                job.status='cancelled'; job.lease_until=None; job.finished_at=now(); return
            key=asset.storage_key; expected=asset.sha256; declared=u.declared_bytes
            owner=album.owner_id; album_id=album.id; page_id=page.id
            saved=u.validation_config or {}
            snapshot=saved.get('media',saved)
            if isinstance(snapshot,dict):
                # Unversioned reservations must reproduce pre-upgrade bytes at
                # immutable keys, including a crash after object persistence.
                # Never replace missing legacy settings with current settings.
                snapshot={'NORMALIZATION_VERSION':1,'NORMALIZED_WEBP_QUALITY':90,**snapshot}
            config_version=saved.get('version',1)
        emit('validation.claim', job_id=claim.job_id, queue_age_ms=max(0,(now()-job.created_at).total_seconds()*1000), attempt_no=job.attempt_count)
        error=None; normalized=None
        keys={role:storage_key(owner,album_id,page_id,role) for role in ('normalized','thumbnail')}
        try:
            if config_version!=1 or saved.get('storage_mode','local')!=self.store.mode:
                raise MediaValidationError('IMAGE_NORMALIZATION_FAILED')
            with span('validation.input', job_id=claim.job_id):
                source = await asyncio.to_thread(self.store.read_bytes,key)
                size = len(source)
                checksum = hashlib.sha256(source).hexdigest()
            if size!=declared or size>20971520: raise MediaValidationError('IMAGE_SIZE_LIMIT_EXCEEDED')
            if expected is None or checksum!=expected: raise MediaValidationError('IMAGE_DECODE_FAILED')
            async with input_file(source) as source_path:
                mime=await asyncio.to_thread(source_mime,source_path)
                with span('media.normalize', job_id=claim.job_id, bytes=size):
                    normalized=await normalize_in_process(source_path,'source',config=snapshot)
                hints=await asyncio.to_thread(preprocessing_hints,saved,mime,source_path)
                if (hints and hints.original_width*4==hints.original_height*3
                    and normalized.width*4!=normalized.height*3):
                    raise MediaValidationError('IMAGE_NORMALIZATION_FAILED')
            if normalized.sha256!=expected:
                raise MediaValidationError('IMAGE_DECODE_FAILED')
            # Deterministic object names and no-overwrite writes make restart idempotent.
            with span('validation.persist', job_id=claim.job_id):
                await asyncio.to_thread(self.store.write,keys['normalized'],normalized.webp_bytes)
                await asyncio.to_thread(self.store.write,keys['thumbnail'],normalized.thumbnail_bytes)
            with Image.open(BytesIO(normalized.thumbnail_bytes)) as thumb: thumb_size=thumb.size
        except StorageUnavailable: raise
        except MediaValidationError as exc: error=exc.code
        except FileNotFoundError: error='IMAGE_DECODE_FAILED'
        except (OSError,ValueError): error='IMAGE_NORMALIZATION_FAILED'
        emit('validation.result', job_id=claim.job_id, outcome='error' if error else 'succeeded', error_code=error)
        clean=False
        async with self.sessions() as s,s.begin():
            album,u,page,asset,job,valid,active=await self._rows(s,claim)
            if not valid: return # New owner may be reusing the same deterministic objects.
            if not active:
                job.status='cancelled'; job.lease_until=None; job.finished_at=now(); clean=True
            elif error:
                u.status='rejected'; u.error_code=error; asset.status='rejected'; clean=True
                job.status='failed'; job.error_code=error; job.lease_until=None; job.finished_at=now()
                bump_version(s, page)
                touch(s, album); await finish_batch(s,album,u.batch_id)
            else:
                for role,data,dimensions in [('normalized',normalized.webp_bytes,(normalized.width,normalized.height)),('thumbnail',normalized.thumbnail_bytes,thumb_size)]:
                    identity=uuid5(NAMESPACE_URL,keys[role])
                    derived=await s.get(MediaAsset,identity)
                    if derived is None:
                        derived=MediaAsset(id=identity,owner_id=owner,album_id=album_id,page_id=page_id,role=role,storage_key=keys[role],mime='image/webp',status='ready',bytes=len(data),width=dimensions[0],height=dimensions[1],sha256=hashlib.sha256(data).hexdigest())
                        s.add(derived); await s.flush()
                    if (derived.owner_id!=owner or derived.album_id!=album_id or derived.page_id!=page_id or derived.deleted_at is not None
                        or derived.sha256!=hashlib.sha256(data).hexdigest()): raise ValueError('derived scope/checksum conflict')
                    setattr(page,role+'_asset_id',identity)
                asset.mime=mime; asset.bytes=size; asset.sha256=expected; asset.status='ready'
                page.input_is_3_4=(hints.original_width*4==hints.original_height*3) if hints else normalized.input_is_3_4
                page.captured_at_raw=hints.captured_at_raw if hints else normalized.captured_at_raw
                page.captured_timezone=hints.captured_timezone if hints else normalized.captured_timezone
                page.sort_date,page.sort_date_source=sort_date(page.captured_at_raw,u.file_last_modified_at,u.created_at)
                u.status='ready'; u.error_code=None
                bump_version(s, page)
                touch(s, album)
                job.status='succeeded'; job.lease_until=None; job.finished_at=now()
                await s.flush(); await finish_batch(s,album,u.batch_id)
                if (u.validation_config or {}).get('source_lifetime')=='temporary':
                    await enqueue_job(s,'cleanup_asset',asset.id)
        if clean:
            for derived_key in keys.values(): await asyncio.to_thread(self.store.delete,derived_key)

    async def scan_incomplete_uploads(self,stamp,limit=100):
        """Sweep durable deletion tombstones, then apply the separate 24h policy."""
        if not 1 <= limit <= 100:
            raise ValueError('scan limit must be between 1 and 100')
        count = await self._scan_deleted_assets(limit)
        cutoff=stamp-timedelta(hours=24)
        async with self.sessions() as s:
            candidates=list((await s.execute(select(Upload.id,Upload.album_id).join(MediaAsset,MediaAsset.id==Upload.asset_id)
                .where(Upload.status.in_(['reserved','expired','rejected']),Upload.created_at<=cutoff,MediaAsset.deleted_at.is_(None))
                .order_by(Upload.created_at,Upload.id).limit(limit))).all())
        for upload_id,album_id in candidates:
            async with self.sessions() as s,s.begin():
                album=await s.scalar(select(Album).where(Album.id==album_id).with_for_update())
                upload=await s.scalar(select(Upload).where(Upload.id==upload_id).with_for_update())
                if album is None or upload is None or album.deleted_at is not None: continue
                page=await s.get(Page,upload.page_id);asset=await s.get(MediaAsset,upload.asset_id)
                if (upload.status not in {'reserved','expired','rejected'} or upload.created_at>cutoff
                    or page is None or page.removed_at is not None or page.album_id!=album.id or asset is None or asset.owner_id!=album.owner_id
                    or asset.album_id!=album.id or asset.page_id!=page.id or page.source_asset_id!=asset.id
                    or asset.role!='source' or asset.deleted_at is not None
                    or asset.storage_key!=storage_key(album.owner_id,album.id,page.id,'source')): continue
                validation=await s.scalar(select(Job).where(Job.kind=='validate_upload',Job.target_id==upload.id).with_for_update())
                if validation and validation.status in {'queued','running','retry_wait'}: continue
                if upload.status=='reserved':
                    upload.status='expired'
                    bump_version(s, page)
                    touch(s, album)
                    await s.flush();await finish_batch(s,album,upload.batch_id)
                await enqueue_job(s,'cleanup_asset',asset.id);count+=1
        return count

    async def _scan_deleted_assets(self, limit):
        """A bounded rotating UUID sweep revisits even already-finished cleanup jobs.

        The DB tombstone survives crashes; the cursor is only a fairness hint and
        resets on restart/wrap. Files may arrive after ANY previous cleanup, so a
        tombstone is not permanently excluded just because its files were absent.
        """
        query = (select(MediaAsset.id, MediaAsset.album_id)
            .join(Album, Album.id == MediaAsset.album_id)
            .join(Page, Page.id == MediaAsset.page_id)
            .where(MediaAsset.owner_id == Album.owner_id, Page.album_id == Album.id,
                MediaAsset.role.in_(['source', 'normalized', 'thumbnail', 'result', 'transform_output']),
                or_(MediaAsset.deleted_at.is_not(None), Album.deleted_at.is_not(None), Page.removed_at.is_not(None)))
            .order_by(MediaAsset.id).limit(limit))
        async with self.sessions() as session:
            after = self._deleted_scan_after
            rows = list((await session.execute(query.where(MediaAsset.id > after) if after else query)).all())
            if not rows and after is not None:
                rows = list((await session.execute(query)).all())
        self._deleted_scan_after = rows[-1].id if len(rows) == limit else None
        count = 0
        # Only this sweep shares observations. The next sweep must discover late PUTs.
        existence = {}
        for asset_id, album_id in rows:
            async with self.sessions() as session:
                album = await session.get(Album, album_id)
                asset = await session.get(MediaAsset, asset_id)
                page = await session.get(Page, asset.page_id) if asset else None
                keys = await self._cleanup_keys(session, album, page, asset)
            if not keys:
                continue
            # Neither file checks nor file removal hold DB row locks.
            try:
                present = False
                for key in keys:
                    if key not in existence:
                        if self.store.mode == 'r2':
                            existence[key] = await asyncio.to_thread(self.store.exists, key)
                        else:
                            existence[key] = await asyncio.to_thread(lambda: self.store.path(key).is_file())
                    if existence[key]:
                        present = True
                        break
            except StorageUnavailable:
                raise
            except (ValueError, OSError):
                continue
            if not present:
                continue
            async with self.sessions() as session, session.begin():
                album = await session.scalar(select(Album).where(Album.id == album_id).with_for_update())
                asset = await session.get(MediaAsset, asset_id)
                page = await session.get(Page, asset.page_id) if asset else None
                if asset is None or not (asset.deleted_at or (album and album.deleted_at) or (page and page.removed_at)):
                    continue
                if not await self._cleanup_keys(session, album, page, asset):
                    continue
                await enqueue_job(session, 'cleanup_asset', asset_id)
                count += 1
        return count

    async def _cleanup_keys(self, session, album, page, asset, *, lock=False):
        """Same scoped eligibility for the sweep and the fenced deletion handler."""
        if (album is None or asset is None or page is None or asset.owner_id != album.owner_id
            or asset.album_id != album.id or page.album_id != album.id
            or asset.role not in {'source', 'normalized', 'thumbnail', 'result', 'transform_output'}):
            return ()
        expected = asset.storage_key
        if expected not in canonical_asset_keys(album.owner_id, album.id, page.id, asset.role):
            return ()
        deleted = album.deleted_at is not None or page.removed_at is not None
        if not deleted:
            linked = await session.scalar(select(Page.id).where(or_(Page.source_asset_id == asset.id,
                Page.normalized_asset_id == asset.id, Page.thumbnail_asset_id == asset.id, Page.result_asset_id == asset.id)))
            task = await session.scalar(select(Task.id).where(Task.output_asset_id == asset.id))
            attempt = await session.scalar(select(Attempt.id).where(Attempt.output_asset_id == asset.id))
            incomplete = False
            retired = False
            if asset.role == 'source' and not task and not attempt:
                query = select(Upload).where(Upload.asset_id == asset.id, Upload.album_id == album.id)
                upload = await session.scalar(query.with_for_update() if lock else query)
                if (upload and upload.page_id == page.id and upload.status=='ready'
                    and (upload.validation_config or {}).get('source_lifetime')=='temporary'
                    and page.source_asset_id==asset.id):
                    normalized=await session.get(MediaAsset,page.normalized_asset_id) if page.normalized_asset_id else None
                    validation=await session.scalar(select(Job).where(Job.kind=='validate_upload',Job.target_id==upload.id))
                    retired=(normalized is not None and normalized.role=='normalized'
                        and normalized.owner_id==album.owner_id and normalized.album_id==album.id
                        and normalized.page_id==page.id and normalized.status=='ready'
                        and normalized.deleted_at is None and normalized.mime=='image/webp'
                        and normalized.bytes is not None and normalized.bytes>0 and bool(normalized.sha256)
                        and normalized.storage_key==storage_key(album.owner_id,album.id,page.id,'normalized')
                        and validation is not None and validation.status=='succeeded')
                if (upload and upload.page_id == page.id and upload.status in {'expired', 'rejected'}
                    and upload.created_at <= now() - timedelta(hours=24)):
                    query = select(Job).where(Job.kind == 'validate_upload', Job.target_id == upload.id)
                    validation = await session.scalar(query.with_for_update() if lock else query)
                    incomplete = validation is None or validation.status in {'succeeded', 'failed', 'cancelled'}
            if (linked or task or attempt) and not (incomplete or retired):
                return ()
        keys = [expected]
        if deleted:
            # Covers unlinked files written by an interrupted validation worker.
            keys.extend(storage_key(album.owner_id, album.id, page.id, role) for role in ('normalized', 'thumbnail', 'transform_output', 'result', 'result_thumbnail'))
        return tuple(dict.fromkeys(keys))

    async def cleanup_album(self,claim):
        async with self.sessions() as s,s.begin():
            album=await s.scalar(select(Album).where(Album.id==claim.target_id).with_for_update())
            if album is None or album.deleted_at is None or album.status!='deleted':
                targets=[]
            else:
                targets=list((await s.scalars(select(MediaAsset.id).where(MediaAsset.album_id==album.id,MediaAsset.owner_id==album.owner_id))).all())
        for asset_id in targets: await self._cleanup(asset_id,claim)
        async with self.sessions() as s: await finish_job(s,claim,now())

    async def _cleanup(self,asset_id,claim=None):
        async with self.sessions() as s,s.begin():
            album_id=await s.scalar(select(MediaAsset.album_id).where(MediaAsset.id==asset_id))
            album=await s.scalar(select(Album).where(Album.id==album_id).with_for_update()) if album_id else None
            if claim is not None:
                job=await s.scalar(select(Job).where(Job.id==claim.job_id).with_for_update())
                if (job is None or job.status!='running' or job.fence_version!=claim.fence_version
                    or job.lease_until is None or job.lease_until<=now()): return
            asset=await s.get(MediaAsset,asset_id)
            page=await s.get(Page,asset.page_id) if asset else None
            keys = await self._cleanup_keys(s, album, page, asset, lock=True)
            if not keys: return
            asset.status='deleted'; asset.deleted_at=asset.deleted_at or now()
        for key in keys:
            await asyncio.to_thread(self.store.delete, key)

    async def cleanup_asset(self,claim):
        await self._cleanup(claim.target_id,claim)
        async with self.sessions() as s: await finish_job(s,claim,now())
