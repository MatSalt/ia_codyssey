"""Source-free generation and crash recovery use only normalized durable input."""
from datetime import datetime, timezone
from uuid import UUID
import asyncio
import pytest
from sqlalchemy import select
from backend.models import Album, MediaAsset, Run
from backend.tests.integration.test_auth_http import client, config
from backend.tests.integration.test_validation_worker import pending
from backend.tests.integration.test_generation_http import generate, resume
from backend.tests.integration.test_generation_pipeline import drain, preserved_original
from backend.uploads.validation import ValidationWorker


@pytest.mark.asyncio
@pytest.mark.parametrize('kind,stage', [('PNG','caption'),('JPEG','image_transform')])
async def test_generation_and_original_attempt_recovery_after_source_retirement(client,db,kind,stage):
    from backend.generation.fake_adapter import FakeExecutor
    from backend.generation.repository import settle_task
    from backend.worker.runner import Runner,ResultStore,utcnow
    client._transport.app.state.settings.dev_ai_enabled=True
    me,album,entry,_,_=await pending(client,kind)
    worker=ValidationWorker(db,config())
    assert await worker.run_once(); assert await worker.run_once()
    async with db() as session:
        source=await session.get(MediaAsset,UUID(entry['asset_id']))
        assert not worker.store.path(source.storage_key).exists()
        version=(await session.get(Album,UUID(album))).version
    response=await generate(client,me,album,version)
    assert response.status_code==202,response.text
    run_id=UUID(response.json()['data']['run_id'])
    executor=FakeExecutor(db,worker.store)
    runner=Runner(db,ResultStore(worker.store.root),executor,local_executor=executor)
    claim,_,_=await preserved_original(db,runner,executor,run_id,stage)
    async with db() as session:
        assert await settle_task(session,claim.task_id,claim.fence_version,'unknown',utcnow())
    assert await runner.recover()==1
    await drain(runner)
    if kind=='JPEG':
        # Recovery preserves the original result; unsent AI still needs explicit resume.
        async with db() as session:
            assert (await session.get(Run,run_id)).status=='action_required'
            version=(await session.get(Album,UUID(album))).version
        assert (await resume(client,me,album,str(run_id),version)).status_code==202
        await drain(runner)
    async with db() as session:
        assert (await session.get(Run,run_id)).status=='succeeded'
        assert (await session.get(Album,UUID(album))).status=='review_ready'
    assert not worker.store.path(source.storage_key).exists()


@pytest.mark.asyncio
async def test_inflight_local_put_after_retirement_is_fenced(client,db,monkeypatch):
    from backend.tests.integration.test_upload_http import setup,consent,reserve,file,headers
    from backend.tests.integration.test_validation_worker import image_bytes
    from backend.models import Upload
    me,album=await setup(client);await consent(client,me)
    data=image_bytes('PNG')
    entry=(await reserve(client,me,album,[file(size=len(data))])).json()['data']['uploads'][0]
    worker=ValidationWorker(db,config())
    async with db() as session:
        source=await session.get(MediaAsset,UUID(entry['asset_id']));key=source.storage_key
    started,resume=asyncio.Event(),asyncio.Event()
    async def stream():
        started.set();await resume.wait();yield data
    request=asyncio.create_task(client.put(entry['upload_url'],content=stream(),headers={**entry['required_headers'],**headers(me)}))
    try:
        await asyncio.wait_for(started.wait(),5)
        worker.store.write(key,data) # another concurrent identical PUT completes first
        path=f'/api/v1/albums/{album}/uploads/{entry["upload_id"]}/complete'
        assert (await client.post(path,json={},headers=headers(me))).status_code==202
        assert await worker.run_once();assert await worker.run_once()
        assert not worker.store.path(key).exists()
        resume.set()
        response=await asyncio.wait_for(request,5)
        assert response.status_code==409
        assert not worker.store.path(key).exists()
    finally:
        resume.set()
        if not request.done():request.cancel()
        await asyncio.gather(request,return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize('snapshot_shape', ['nested', 'flat', 'empty'])
async def test_legacy_codec_crash_retry_preserves_existing_objects(client, db, monkeypatch, snapshot_shape):
    """Old objects written before a crash survive an upgraded worker's retry."""
    from datetime import timedelta
    from io import BytesIO
    import hashlib
    import os
    from PIL import Image
    from backend.media.normalize_v1 import normalize as legacy_normalize
    from backend.media.process import MEDIA_ENV_KEYS
    from backend.models import Upload, Page, Job
    from backend.storage.local import storage_key
    from backend.tests.integration.test_upload_http import setup, consent, reserve, file, headers
    from backend.worker.jobs import claim_job, recover_jobs
    import backend.uploads.validation as validation

    me, album = await setup(client)
    await consent(client, me)
    pixels = bytes((index * 37 + index // 97) % 256 for index in range(640 * 480 * 3))
    out = BytesIO()
    Image.frombytes('RGB', (640, 480), pixels).save(out, format='PNG')
    data = out.getvalue()
    response = await reserve(client, me, album, [file('legacy.png', len(data))])
    assert response.status_code == 201
    entry = response.json()['data']['uploads'][0]
    assert (await client.put(entry['upload_url'], content=data,
        headers={**entry['required_headers'], **headers(me)})).status_code == 204
    path = f'/api/v1/albums/{album}/uploads/{entry["upload_id"]}'
    assert (await client.post(path+'/complete', json={}, headers=headers(me))).status_code == 202
    # Real pre-upgrade snapshots have neither codec version nor quality.
    media = {'NORMALIZED_WEBP_LOSSLESS': True, 'NORMALIZED_MAX_EDGE': 256,
             'NORMALIZED_MAX_BYTES': 20971520, 'THUMBNAIL_WEBP_QUALITY': 73,
             'THUMBNAIL_MAX_EDGE': 128, 'RESULT_WEBP_QUALITY': 90}
    saved = {'version': 1, 'storage_mode': 'local', 'media': media} if snapshot_shape == 'nested' else (
        media if snapshot_shape == 'flat' else {})
    async with db() as session, session.begin():
        upload = await session.get(Upload, UUID(entry['upload_id']))
        upload.validation_config = saved
        source = await session.get(MediaAsset, upload.asset_id)
        keys = {role: storage_key(source.owner_id, source.album_id, source.page_id, role)
                for role in ('normalized', 'thumbnail')}
        source_key = source.storage_key
    # Produce bytes directly with the frozen old implementation, independently
    # of the upgraded subprocess router under test.
    with monkeypatch.context() as old_environment:
        for key in MEDIA_ENV_KEYS:
            old_environment.delenv(key, raising=False)
        if snapshot_shape != 'empty':
            for key, value in media.items():
                old_environment.setenv(key, str(value).lower())
        old = legacy_normalize(data, 'legacy.png')
    worker = ValidationWorker(db, config())
    stamp = datetime.now(timezone.utc)
    async with db() as session:
        claim = await claim_job(session, stamp-timedelta(minutes=5), 1, ('validate_upload',))
    assert claim is not None
    expected = {'normalized': old.webp_bytes, 'thumbnail': old.thumbnail_bytes}
    for role, content in expected.items():
        worker.store.write(keys[role], content)
    # Crash before DB settlement, followed by deployment configuration changes.
    for key in MEDIA_ENV_KEYS:
        monkeypatch.setenv(key, '2' if key == 'NORMALIZATION_VERSION' else (
            'false' if key == 'NORMALIZED_WEBP_LOSSLESS' else '12'))
    parent_environment = {key: os.environ[key] for key in MEDIA_ENV_KEYS}
    seen = []
    real = validation.normalize_in_process
    async def capture(*args, **kwargs):
        seen.append(kwargs['config'])
        return await real(*args, **kwargs)
    monkeypatch.setattr(validation, 'normalize_in_process', capture)
    async with db() as session:
        assert await recover_jobs(session, stamp) == 1
    assert await worker.run_once()
    assert (await client.get(path)).json()['data']['status'] == 'ready'
    assert seen[0]['NORMALIZATION_VERSION'] == 1
    assert seen[0]['NORMALIZED_WEBP_QUALITY'] == 90
    assert {key: os.environ[key] for key in MEDIA_ENV_KEYS} == parent_environment
    async with db() as session:
        upload = await session.get(Upload, UUID(entry['upload_id']))
        page = await session.get(Page, upload.page_id)
        job = await session.get(Job, claim.job_id)
        assert upload.validation_config == saved
        assert job.status == 'succeeded' and job.attempt_count == 2
        for role, content in expected.items():
            asset = await session.get(MediaAsset, getattr(page, role+'_asset_id'))
            assert asset.sha256 == hashlib.sha256(content).hexdigest()
            assert worker.store.read_bytes(keys[role]) == content
        assert await session.scalar(select(Job).where(Job.kind == 'cleanup_asset')) is None
    assert worker.store.read_bytes(source_key) == data
