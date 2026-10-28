"""Explicit local fake executor. Immutable inputs, fenced persistence, no network."""
import asyncio
import hashlib
from io import BytesIO
from datetime import datetime,timezone
from uuid import UUID,uuid5,NAMESPACE_URL
from PIL import Image
from sqlalchemy import select
from backend.models import Album,Page,Run,Task,Attempt,MediaAsset
from backend.storage.local import storage_key
from backend.storage.factory import result_store
from backend.storage.r2 import StorageUnavailable
from backend.storage.snapshot import input_file
from backend.telemetry import span
from backend.generation.repository import _locked_task,_active
from backend.media.fake_transform import fake_transform,optimize_in_process

CAPTION='함께한 순간이 오래도록 마음에 남아요.'


class FakeExecutionError(Exception):
    def __init__(self,code,*,safe_to_retry=False):
        super().__init__(code)
        self.code=code;self.safe_to_retry=safe_to_retry
        # A fake precondition failure cannot have sent an external request.
        self.dispatch_state='not_sent'


class FakeExecutor:
    execution_mode = 'local_fake'
    def __init__(self,sessions,store):
        self.sessions=sessions;self.store=store

    def accepts_config(self,config):
        return (config.get('execution_mode')=='local_fake'
            and config.get('image_provider')=='local_fake' and config.get('caption_provider')=='local_fake'
            and config.get('image_model')=='fake-canvas-v1' and config.get('caption_model')=='fake-sentence-v1')

    async def _context(self,attempt_id,stage,*,recover=False):
        async with self.sessions() as s,s.begin():
            attempt=await s.get(Attempt,attempt_id)
            if attempt is None:raise FakeExecutionError('MEDIA_SAVE_FAILED')
            rows=await _locked_task(s,attempt.task_id)
            album,run,task,page=rows
            valid=(_active(*rows,attempt.fence_version,datetime.now(timezone.utc))
                if not recover else task.status in {'unknown','running'} and album.deleted_at is None
                and album.status!='deleted' and page.removed_at is None and run.status!='cancelled')
            snapshot=next((x for x in run.input_snapshot if x['page_id']==str(page.id)),None)
            if (not valid or attempt.attempt_no!=task.attempt_count or task.stage!=stage or snapshot is None
                or not self.accepts_config(run.config_snapshot)):
                raise FakeExecutionError('MEDIA_SAVE_FAILED')
            asset=await s.get(MediaAsset,UUID(snapshot['normalized_asset_id']))
            if (asset is None or asset.owner_id!=album.owner_id or asset.album_id!=album.id or asset.page_id!=page.id
                or asset.role!='normalized' or asset.status!='ready' or asset.deleted_at is not None
                or asset.mime!='image/webp' or asset.sha256!=snapshot['sha256']
                or asset.storage_key!=storage_key(album.owner_id,album.id,page.id,'normalized')):
                raise FakeExecutionError('MEDIA_SAVE_FAILED')
            input_asset=asset
            if stage=='optimize':
                image=await s.scalar(select(Task).where(Task.run_id==run.id,Task.page_id==page.id,Task.stage=='image_transform'))
                input_asset=await s.get(MediaAsset,image.output_asset_id) if image and image.status=='succeeded' and image.output_asset_id else None
                expected_role='normalized' if snapshot['input_is_3_4'] else 'transform_output'
                if (input_asset is None or input_asset.role!=expected_role or input_asset.owner_id!=album.owner_id
                    or input_asset.album_id!=album.id or input_asset.page_id!=page.id or input_asset.status!='ready'
                    or input_asset.deleted_at is not None or input_asset.mime!='image/webp'
                    or input_asset.storage_key!=storage_key(album.owner_id,album.id,page.id,expected_role)):
                    raise FakeExecutionError('MEDIA_SAVE_FAILED')
            return {'owner':album.owner_id,'album':album.id,'page':page.id,'task':task.id,'attempt':attempt.id,
                'fence':attempt.fence_version,'attempt_no':attempt.attempt_no,'config':run.config_snapshot,
                'original_output_id':attempt.output_asset_id,
                'normalized_key':asset.storage_key,'normalized_sha':snapshot['sha256'],'normalized_bytes':asset.bytes,
                'key':input_asset.storage_key,'sha':input_asset.sha256,'bytes':input_asset.bytes}

    async def _verify(self,context):
        snapshots = {}
        for key,sha,size in [(context['normalized_key'],context['normalized_sha'],context['normalized_bytes']),
                             (context['key'],context['sha'],context['bytes'])]:
            try:
                if key not in snapshots:
                    snapshots[key] = await asyncio.to_thread(self.store.read_bytes,key)
                data = snapshots[key]
            except StorageUnavailable:raise
            except (OSError,ValueError):raise FakeExecutionError('MEDIA_SAVE_FAILED') from None
            if len(data)!=size or hashlib.sha256(data).hexdigest()!=sha:
                raise FakeExecutionError('MEDIA_SAVE_FAILED')
        return snapshots

    async def _persist(self,context,kind,data,*,recover=False):
        role='thumbnail' if kind=='result_thumbnail' else kind
        key=storage_key(context['owner'],context['album'],context['page'],kind)
        identity=uuid5(NAMESPACE_URL,key)
        def metadata():
            with Image.open(BytesIO(data)) as image:
                if image.format!='WEBP' or image.width*4!=image.height*3:raise FakeExecutionError('IMAGE_RATIO_INVALID')
                image.load()
                return image.size
        width,height=await asyncio.to_thread(metadata)
        sha=hashlib.sha256(data).hexdigest()
        # Pending metadata gives recovery a scoped anchor for files saved before a crash.
        async with self.sessions() as s,s.begin():
            rows=await _locked_task(s,context['task'])
            album,run,task,page=rows
            if (album.deleted_at is not None or page.removed_at is not None or run.status=='cancelled'
                or not self.accepts_config(run.config_snapshot)
                or task.attempt_count!=context['attempt_no']
                or (not recover and not _active(*rows,context['fence'],datetime.now(timezone.utc)))):
                raise FakeExecutionError('MEDIA_SAVE_FAILED')
            asset=await s.get(MediaAsset,identity)
            if asset is None:
                asset=MediaAsset(id=identity,owner_id=album.owner_id,album_id=album.id,page_id=page.id,role=role,
                    storage_key=key,mime='image/webp',status='pending')
                s.add(asset);await s.flush()
            if (asset.owner_id!=album.owner_id or asset.album_id!=album.id or asset.page_id!=page.id
                or asset.role!=role or asset.storage_key!=key or asset.deleted_at is not None
                or asset.sha256 is not None and asset.sha256!=sha):
                raise FakeExecutionError('MEDIA_SAVE_FAILED')
            asset.bytes=len(data);asset.width=width;asset.height=height;asset.sha256=sha
            if kind in {'transform_output','result'}:
                attempt=await s.get(Attempt,context['attempt'])
                if attempt.output_asset_id not in {None,identity}:raise FakeExecutionError('MEDIA_SAVE_FAILED')
                attempt.output_asset_id=identity
        await asyncio.to_thread(self.store.write,key,data)
        async with self.sessions() as s,s.begin():
            album,run,task,page=await _locked_task(s,context['task'])
            asset=await s.get(MediaAsset,identity)
            if (album.deleted_at is not None or page.removed_at is not None or run.status=='cancelled'
                or not self.accepts_config(run.config_snapshot)
                or task.attempt_count!=context['attempt_no']
                or (not recover and not _active(album,run,task,page,context['fence'],datetime.now(timezone.utc)))):
                from backend.worker.jobs import enqueue_job
                await enqueue_job(s,'cleanup_asset',identity)
                return None
            if asset.sha256 is not None and asset.sha256!=sha:raise FakeExecutionError('MEDIA_SAVE_FAILED')
            asset.bytes=len(data);asset.width=width;asset.height=height;asset.sha256=sha;asset.status='ready'
        return identity

    async def execute(self,attempt_id,stage):
        context=await self._context(attempt_id,stage)
        try:
            snapshots = await self._verify(context)
        except StorageUnavailable:
            # No result or external request exists at this input-only boundary.
            raise FakeExecutionError('MEDIA_SAVE_FAILED',safe_to_retry=True) from None
        if stage=='caption':
            result={'caption':CAPTION}
        elif stage=='image_transform':
            try:
                async with input_file(snapshots[context['key']]) as source_path:
                    with span('media.fake_transform'):
                        data=await fake_transform(source_path,max_edge=min(context['config'].get('normalized_max_edge',4096),4096))
            except StorageUnavailable:
                # Local fake bytes are disposable until persistence starts. Do not
                # extend this handler over _persist, envelope writes or recovery.
                raise FakeExecutionError('MEDIA_SAVE_FAILED',safe_to_retry=True) from None
            asset_id=await self._persist(context,'transform_output',data)
            if asset_id is None:raise FakeExecutionError('MEDIA_SAVE_FAILED')
            result={'asset_id':str(asset_id)}
        elif stage=='optimize':
            try:
                async with input_file(snapshots[context['key']]) as source_path:
                    with span('media.optimize'):
                        data,thumb,_=await optimize_in_process(source_path,context['config'])
                asset_id=await self._persist(context,'result',data)
                thumb_id=await self._persist(context,'result_thumbnail',thumb)
                if asset_id is None or thumb_id is None:raise FakeExecutionError('MEDIA_SAVE_FAILED')
                result={'asset_id':str(asset_id),'thumbnail_asset_id':str(thumb_id)}
            except StorageUnavailable:raise
            except OSError:raise FakeExecutionError('MEDIA_SAVE_FAILED',safe_to_retry=True) from None
        else:raise FakeExecutionError('MEDIA_SAVE_FAILED')
        # Same durable envelope as Runner; a crash after this write needs no adapter call.
        await result_store(self.store).save(str(attempt_id),result)
        return result

    async def recover_original(self,attempt_id,stage):
        """Recover only an already written image response; never synthesize/re-send."""
        if stage!='image_transform':return None
        try:
            context=await self._context(attempt_id,stage,recover=True)
            await self._verify(context)
            key=storage_key(context['owner'],context['album'],context['page'],'transform_output')
            if context['original_output_id']!=uuid5(NAMESPACE_URL,key):return None
            data=await asyncio.to_thread(lambda:self.store.path(key).read_bytes())
            asset_id=await self._persist(context,'transform_output',data,recover=True)
            return {'asset_id':str(asset_id)} if asset_id else None
        except StorageUnavailable:raise
        except (OSError,ValueError,FakeExecutionError):return None
