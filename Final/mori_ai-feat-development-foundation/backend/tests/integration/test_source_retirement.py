"""New validated source bytes retire without losing completion or recovery state."""
from datetime import datetime, timezone
from uuid import UUID
import pytest
from sqlalchemy import select
from backend.models import MediaAsset, Upload, Job
from backend.tests.integration.test_auth_http import client, config
from backend.tests.integration.test_album_http import headers
from backend.tests.integration.test_validation_worker import pending
from backend.uploads.validation import ValidationWorker
from backend.worker.jobs import claim_job


@pytest.mark.asyncio
async def test_source_retirement_replay_and_late_put_sweep(client,db):
    me,album,entry,path,data=await pending(client)
    worker=ValidationWorker(db,config())
    assert await worker.run_once()
    async with db() as session:
        asset=await session.get(MediaAsset,UUID(entry['asset_id']))
        key=asset.storage_key
        cleanup=await session.scalar(select(Job).where(Job.kind=='cleanup_asset',Job.target_id==asset.id))
        assert cleanup is not None
        assert worker.store.path(key).exists() # validation transaction committed before cleanup
    assert await worker.run_once()
    assert not worker.store.path(key).exists()
    replay=await client.post(path+'/complete',json={},headers=headers(me))
    assert replay.status_code == 200 and replay.json()['data']['status'] == 'ready'
    assert (await client.put(entry['upload_url'],content=data,headers={**entry['required_headers'],**headers(me)})).status_code in (404,409)
    worker.store.write(key,data) # outstanding direct PUT after first cleanup / process crash
    worker=ValidationWorker(db,config())
    assert await worker.scan_incomplete_uploads(datetime.now(timezone.utc)) == 1
    assert await worker.run_once()
    assert not worker.store.path(key).exists()
    async with db() as session:
        upload=await session.get(Upload,UUID(entry['upload_id']))
        assert upload.status=='ready' and upload.declared_bytes==len(data)
        asset=await session.get(MediaAsset,upload.asset_id)
        assert asset.sha256 and asset.bytes==len(data)


@pytest.mark.asyncio
async def test_retirement_stale_fence_does_not_delete_source(client,db):
    _,_,entry,_,_=await pending(client)
    worker=ValidationWorker(db,config()); assert await worker.run_once()
    async with db() as session:
        claim=await claim_job(session,datetime.now(timezone.utc),90,('cleanup_asset',))
    assert claim is not None
    async with db() as session,session.begin():
        (await session.get(Job,claim.job_id)).fence_version+=1
    await worker.cleanup_asset(claim)
    async with db() as session:
        asset=await session.get(MediaAsset,UUID(entry['asset_id']))
        assert asset.deleted_at is None and worker.store.path(asset.storage_key).exists()


@pytest.mark.asyncio
@pytest.mark.parametrize('protected', ['legacy', 'normalized_missing', 'normalized_foreign', 'validation_running', 'task', 'attempt'])
async def test_cleanup_preserves_unproven_or_legacy_sources(client,db,protected):
    from backend.models import Page, Run, Task, Attempt
    from backend.worker.jobs import enqueue_job
    from uuid import uuid4
    _,album,entry,_,_=await pending(client)
    worker=ValidationWorker(db,config()); assert await worker.run_once()
    async with db() as session,session.begin():
        upload=await session.get(Upload,UUID(entry['upload_id']))
        page=await session.get(Page,upload.page_id)
        source=await session.get(MediaAsset,upload.asset_id); key=source.storage_key
        if protected=='legacy':
            upload.validation_config={k:v for k,v in upload.validation_config.items() if k!='source_lifetime'}
        elif protected=='normalized_missing':
            page.normalized_asset_id=None
        elif protected=='normalized_foreign':
            (await session.get(MediaAsset,page.normalized_asset_id)).storage_key=str(uuid4())
        elif protected=='validation_running':
            job=await session.scalar(select(Job).where(Job.kind=='validate_upload'))
            job.status='running'
        else:
            run=Run(album_id=UUID(album),status='action_required');session.add(run);await session.flush()
            task=Task(run_id=run.id,page_id=page.id,stage='caption',status='unknown',
                output_asset_id=source.id if protected=='task' else None)
            session.add(task);await session.flush()
            if protected=='attempt':
                session.add(Attempt(task_id=task.id,attempt_no=1,fence_version=0,status='unknown',output_asset_id=source.id))
        await enqueue_job(session,'cleanup_asset',source.id)
    async with db() as session:
        claim=await claim_job(session,datetime.now(timezone.utc),90,('cleanup_asset',))
    await worker.cleanup_asset(claim)
    assert worker.store.path(key).is_file()
    async with db() as session:
        assert (await session.get(MediaAsset,source.id)).deleted_at is None


@pytest.mark.asyncio
async def test_remote_retirement_replay_hash_and_repeated_late_writes(client,db,tmp_path):
    import hashlib
    from backend.tests.integration.test_r2_pipeline import remote
    from backend.uploads.service import complete_upload
    me,album,entry,_,data=await pending(client)
    store,s3=remote(tmp_path)
    async with db() as session,session.begin():
        upload=await session.get(Upload,UUID(entry['upload_id']))
        upload.validation_config={**upload.validation_config,'storage_mode':'r2'}
        source=await session.get(MediaAsset,upload.asset_id)
        key=source.storage_key
    store.write(key,data)
    worker=ValidationWorker(db,config()); worker.store=store
    assert await worker.run_once(); assert await worker.run_once()
    assert not store.exists(key)
    digest=hashlib.sha256(data).hexdigest()
    calls=len(s3.calls)
    status,body=await complete_upload(db,store,UUID(me['user']['id']),UUID(album),UUID(entry['upload_id']),digest)
    assert status==200 and body['status']=='ready' and len(s3.calls)==calls
    from backend.http.errors import APIError
    with pytest.raises(APIError) as error:
        await complete_upload(db,store,UUID(me['user']['id']),UUID(album),UUID(entry['upload_id']),'0'*64)
    assert error.value.status==409
    for _ in range(2):
        store.write(key,data)
        worker=ValidationWorker(db,config()); worker.store=store
        assert await worker.scan_incomplete_uploads(datetime.now(timezone.utc))==1
        assert await worker.run_once()
        assert not store.exists(key)
