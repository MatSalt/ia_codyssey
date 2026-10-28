"""Generation admission with frozen fake/real mode; caller owns the transaction.

Lock order: User -> Album -> Run -> Task. No executor or file I/O here.
"""
from backend.generation.prompt_profiles import DEFAULT_PROMPT_VERSION, SUPPORTED_PROMPT_VERSIONS
from datetime import datetime, timezone
from sqlalchemy import select
from backend.albums import repository as albums
from backend.auth.repository import get_consent
from backend.http.errors import APIError
from backend.http.idempotency import replay
from backend.http.schemas import CLIENT_CONFIG
from backend.models import Album, Run, Task, Outbox, Attempt, MediaAsset
from backend.generation.resume_policy import eligible_resume_tasks, resume_locked_tasks

ACTIVE_RUNS = ('queued', 'running', 'action_required')


def require_local_ai(settings):
    """Compatibility entrypoint: admit only explicitly enabled fake or real AI."""
    if not getattr(settings, 'ai_real_calls_enabled', False) and (settings.app_env != 'local' or not settings.dev_ai_enabled):
        raise APIError(503, 'TEMPORARILY_UNAVAILABLE', 'AI 생성이 비활성화되어 있습니다.', retryable=False)


async def owned_album(session, owner_id, album_id):
    if await albums.lock_owner(session, owner_id) is None:
        raise APIError(404, 'RESOURCE_NOT_FOUND')
    album = await albums.find_album(session, owner_id, album_id, lock=True)
    if album is None:
        raise APIError(404, 'RESOURCE_NOT_FOUND')
    return album


async def require_consent(session, owner_id, settings):
    if await get_consent(session, owner_id, settings.consent_policy_version) is None:
        raise APIError(403, 'CONSENT_REQUIRED', '사진 업로드와 AI 처리를 위한 최신 동의가 필요합니다.')


def check_version(album, expected_version):
    if album.version != expected_version:
        raise APIError(409, 'VERSION_CONFLICT', details={'resource_type':'album', 'resource_id':str(album.id), 'current_version':album.version})


def config_snapshot(settings):
    """Snapshot mode/models independently from future worker configuration.

    attempt_budget is a local test execution bound, not an operating cost quota.
    """
    snapshot = {
        'snapshot_version':1, 'execution_mode':'local_fake', **CLIENT_CONFIG,
        'image_provider':'local_fake', 'image_model':'fake-canvas-v1',
        'caption_provider':'local_fake', 'caption_model':'fake-sentence-v1',
        'prompt_version':'local-fake-v1', 'target_ratio':'3:4',
        'normalized_webp_lossless':settings.normalized_webp_lossless,
        'normalized_webp_quality':settings.normalized_webp_quality,
        'normalized_max_edge':settings.normalized_max_edge, 'normalized_max_bytes':settings.normalized_max_bytes,
        'result_webp_quality':settings.result_webp_quality, 'thumbnail_webp_quality':settings.thumbnail_webp_quality,
        'thumbnail_max_edge':settings.thumbnail_max_edge,
        'max_attempts':3, 'attempt_budget':450, 'budget_scope':'local_test_bound', 'estimated_cost':0,
        'retry_backoff_seconds':[5,20], 'retry_jitter':True, 'sdk_max_retries':0,
        'image_concurrency':2, 'caption_concurrency':4, 'media_concurrency':1,
        'image_timeout_seconds':300, 'caption_timeout_seconds':60,
        'lease_seconds':90, 'heartbeat_seconds':15,
    }

    if getattr(settings, 'ai_real_calls_enabled', False):
        snapshot.update(execution_mode='openai', image_provider='openai', caption_provider='openai',
            image_model=settings.openai_image_model, caption_model=settings.openai_caption_model,
            prompt_version=DEFAULT_PROMPT_VERSION, pricing_profile='openai-standard-2026-10-16-v1', budget_scope='validation_usd', estimated_cost=None)
    return snapshot


def within_attempt_budget(run, tasks, proposed):
    return sum(t.attempt_count for t in tasks) + proposed <= run.config_snapshot.get('attempt_budget',450)


def eligible_for_run(run, tasks):
    if run.status != 'action_required':
        return []
    eligible = eligible_resume_tasks(tasks, any(t.status == 'unknown' for t in tasks))
    return eligible if within_attempt_budget(run, tasks, len(eligible)) else []


async def check_concurrency(session, owner_id, exclude_run=None):
    query = select(Run.id).join(Album, Album.id == Run.album_id).where(
        Album.owner_id == owner_id, Album.deleted_at.is_(None), Album.status != 'deleted', Run.status.in_(ACTIVE_RUNS))
    if exclude_run is not None:
        query = query.where(Run.id != exclude_run)
    if await session.scalar(query.limit(1)) is not None:
        raise APIError(429, 'CONCURRENCY_LIMIT_EXCEEDED')


async def create_generation(session, owner_id, album_id, expected_version, key, request_hash, settings):
    album = await owned_album(session, owner_id, album_id)
    operation = f'POST /api/v1/albums/{album_id}/generation'
    record = await albums.find_record(session, owner_id, operation, key)
    if record:
        return replay(record, request_hash)
    await require_consent(session, owner_id, settings)
    pages = await albums.album_pages(session, album_id)
    uploads = {u.page_id:u for u in await albums.page_uploads(session,album_id)}
    assets = {a.id:a for a in await albums.ready_assets(session,album_id)}
    # Source rows retain provenance after byte retirement; their scope still matters.
    sources = {a.id:a for a in (await session.scalars(select(MediaAsset).where(
        MediaAsset.album_id==album_id, MediaAsset.owner_id==owner_id, MediaAsset.role=='source'))).all()}
    not_ready = []
    for p in pages:
        upload, normalized = uploads.get(p.id), assets.get(p.normalized_asset_id)
        source = sources.get(p.source_asset_id)
        if (upload is None or upload.status != 'ready' or upload.album_id != album_id
                or upload.asset_id != p.source_asset_id or source is None or source.page_id != p.id
                or normalized is None or normalized.role != 'normalized' or normalized.page_id != p.id
                or normalized.mime != 'image/webp' or not normalized.sha256
                or upload.declared_bytes is None or upload.declared_bytes <= 0 or p.input_is_3_4 is None):
            not_ready.append(str(p.id))
    if not_ready:
        raise APIError(422, 'UPLOAD_NOT_READY', details={'page_ids':not_ready})
    if not CLIENT_CONFIG['album_min_photos'] <= len(pages) <= CLIENT_CONFIG['album_max_photos']:
        raise APIError(422, 'PHOTO_COUNT_EXCEEDED' if len(pages)>CLIENT_CONFIG['album_max_photos'] else 'VALIDATION_ERROR')
    sizes = [uploads[p.id].declared_bytes for p in pages]
    if any(n > CLIENT_CONFIG['upload_max_file_bytes'] for n in sizes):
        raise APIError(413, 'FILE_TOO_LARGE')
    if sum(sizes) > CLIENT_CONFIG['upload_max_album_bytes']:
        raise APIError(413, 'ALBUM_BYTES_EXCEEDED')
    check_version(album, expected_version)
    existing = await session.scalar(select(Run.id).where(Run.album_id == album_id, Run.status != 'cancelled').limit(1))
    if existing is not None:
        raise APIError(409, 'GENERATION_ALREADY_EXISTS')
    if album.status != 'draft':
        raise APIError(409, 'STATE_CONFLICT')
    await check_concurrency(session, owner_id)
    require_local_ai(settings)
    snapshot = [{'page_id':str(p.id), 'position':p.position, 'normalized_asset_id':str(p.normalized_asset_id),
        'sha256':assets[p.normalized_asset_id].sha256, 'input_is_3_4':p.input_is_3_4} for p in pages]
    run = Run(album_id=album_id, status='queued', input_version=album.version,
              input_snapshot=snapshot, config_snapshot=config_snapshot(settings))
    session.add(run); await session.flush()
    tasks=[]
    for p in pages:
        for stage in ('caption','image_transform','optimize'):
            passthrough = stage == 'image_transform' and p.input_is_3_4
            task = Task(run_id=run.id, page_id=p.id, stage=stage,
                status='succeeded' if passthrough else 'queued',
                completion_kind='passthrough' if passthrough else None,
                output_asset_id=p.normalized_asset_id if passthrough else None,
                requires_ai_call=stage != 'optimize' and not passthrough,
                has_persisted_input=True, safe_to_retry=False)
            session.add(task); tasks.append(task)
    await session.flush()
    if not within_attempt_budget(run,tasks,sum(t.status != 'succeeded' for t in tasks)):
        raise APIError(429, 'USAGE_LIMIT_EXCEEDED')
    for task in tasks:
        if task.status == 'queued':
            session.add(Outbox(event_type='task_ready', entity_id=task.id, payload={'task_id':str(task.id)}))
    album.active_run_id = run.id; album.status='processing'; album.version += 1
    album.updated_at = datetime.now(timezone.utc)
    data = acceptance(album,run)
    await albums.save_record(session,owner_id,operation,key,request_hash,album_id,202,data)
    return 202,data


def acceptance(album,run):
    return {'run_id':str(run.id), 'status_url':f'/api/v1/albums/{album.id}/generation?run_id={run.id}', 'album_version':album.version}


async def resume_generation(session, owner_id, album_id, run_id, expected_version, key, request_hash, settings):
    album = await owned_album(session,owner_id,album_id)
    operation = f'POST /api/v1/albums/{album_id}/generation/resume'
    record = await albums.find_record(session,owner_id,operation,key)
    if record:
        return replay(record,request_hash)
    await require_consent(session,owner_id,settings)
    check_version(album,expected_version)
    run = await session.scalar(select(Run).where(Run.id == run_id, Run.album_id == album_id).with_for_update())
    if run is None:
        raise APIError(404, 'GENERATION_NOT_FOUND')
    tasks = (await session.scalars(select(Task).where(Task.run_id == run_id).order_by(Task.id).with_for_update())).all()
    eligible = eligible_resume_tasks(tasks,any(t.status == 'unknown' for t in tasks))
    if album.active_run_id != run.id or album.status != 'action_required' or run.status != 'action_required' or not eligible:
        raise APIError(409,'RESUME_NOT_ALLOWED')
    await check_concurrency(session,owner_id,exclude_run=run_id)
    if not within_attempt_budget(run,tasks,len(eligible)):
        raise APIError(429,'USAGE_LIMIT_EXCEEDED')
    require_local_ai(settings)
    expected = config_snapshot(settings)
    if any(run.config_snapshot.get(k) != expected[k] for k in ('execution_mode','image_model','caption_model')):
        raise APIError(409,'RESUME_NOT_ALLOWED')
    if expected['execution_mode']=='openai' and (run.config_snapshot.get('prompt_version') not in SUPPORTED_PROMPT_VERSIONS
            or run.config_snapshot.get('pricing_profile') != expected['pricing_profile']):
        raise APIError(409,'RESUME_NOT_ALLOWED')
    resumed = resume_locked_tasks(album,run,tasks)
    from backend.worker.jobs import enqueue_job
    for task in tasks:
        if task.id in resumed:
            session.add(Outbox(event_type='task_ready',entity_id=task.id,payload={'task_id':str(task.id)}))
        elif task.status == 'unknown':
            attempt = await session.scalar(select(Attempt).where(Attempt.task_id == task.id).order_by(Attempt.attempt_no.desc()).limit(1))
            if attempt:
                await enqueue_job(session,'reconcile_attempt',attempt.id)
    album.updated_at = datetime.now(timezone.utc)
    data=acceptance(album,run)
    await albums.save_record(session,owner_id,operation,key,request_hash,album_id,202,data)
    return 202,data
