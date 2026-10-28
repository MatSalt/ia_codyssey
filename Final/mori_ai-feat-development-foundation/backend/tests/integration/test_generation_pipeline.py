"""Local fake pipeline with real private files, subprocesses and PostgreSQL."""
import asyncio
import hashlib
from io import BytesIO
from uuid import UUID
import pytest
import pytest_asyncio
import httpx
from PIL import Image
from sqlalchemy import select,func
from backend.models import Album,Run,Task,Attempt,Page,MediaAsset
from backend.tests.integration.test_generation_http import ready_album,generate,resume
from backend.tests.integration.test_album_http import headers
from backend.tests.integration.test_auth_http import config


@pytest_asyncio.fixture
async def client(db,tmp_path):
    from backend.main import create_app
    from backend.tests.integration.test_auth_http import ORIGIN
    app=create_app(settings=config(dev_ai_enabled=True,storage_root=tmp_path/'private'),session_factory=db)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url=ORIGIN) as c:yield c


async def pipeline(client,db,tmp_path,count=2,*,production_schedule=False):
    from backend.storage.local import LocalStorage,storage_key
    from backend.generation.fake_adapter import FakeExecutor
    from backend.worker.runner import Runner,ResultStore
    me,album=await ready_album(client,db,count=count)
    store=LocalStorage(tmp_path/'private')
    async with db() as s,s.begin():
        pages=(await s.scalars(select(Page).order_by(Page.position))).all()
        for page in pages:
            for role in ['source','normalized']:
                asset=await s.get(MediaAsset,getattr(page,role+'_asset_id'))
                out=BytesIO();Image.new('RGB',(30,40) if page.input_is_3_4 else (60,20),'red').save(out,format='WEBP',lossless=True)
                data=out.getvalue();asset.storage_key=storage_key(asset.owner_id,asset.album_id,page.id,role)
                asset.mime='image/webp';asset.bytes=len(data);asset.sha256=hashlib.sha256(data).hexdigest()
                asset.width,asset.height=(30,40) if page.input_is_3_4 else (60,20)
                store.write(asset.storage_key,data)
    admitted=await generate(client,me,album);assert admitted.status_code==202
    run_id=UUID(admitted.json()['data']['run_id'])
    executor=FakeExecutor(db,store)
    schedule={} if production_schedule else {'lease_seconds':2,'heartbeat_seconds':.1}
    runner=Runner(db,ResultStore(store.root),executor,local_executor=executor,**schedule)
    return me,album,run_id,store,executor,runner


async def drain(runner,limit=200):
    for _ in range(limit):
        if not await runner.run_once():return
    raise AssertionError('pipeline did not drain')


async def drain_worker(runner,limit=200):
    # Worker __main__ runs maintenance before each claim. Preserve that recovery
    # step in normal completion/load checks; fast lease/fault tests keep drain().
    for _ in range(limit):
        await runner.maintenance()
        if not await runner.run_once():return
    raise AssertionError('worker pipeline did not drain')


async def pipeline_diagnostics(db,run_id,store):
    """Failure-only execution evidence; never dump photos or caption content."""
    from datetime import datetime,timezone
    from collections import Counter
    async with db() as s:
        run=await s.get(Run,run_id)
        tasks=(await s.scalars(select(Task).where(Task.run_id==run_id))).all()
        attempts=(await s.scalars(select(Attempt).join(Task).where(Task.run_id==run_id))).all()
        result={'now':datetime.now(timezone.utc).isoformat(),'run_status':run.status,
                'task_counts':dict(Counter(t.status for t in tasks)),'unfinished':[]}
        for task in tasks:
            if task.status=='succeeded':continue
            latest=max((a for a in attempts if a.task_id==task.id),key=lambda a:a.attempt_no,default=None)
            result['unfinished'].append({'id':str(task.id),'stage':task.stage,'status':task.status,
                'fence':task.fence_version,'lease':str(task.lease_until),'attempt_count':task.attempt_count,
                'error':task.error_code,'attempt':None if latest is None else {
                    'id':str(latest.id),'status':latest.status,'fence':latest.fence_version,
                    'dispatch_state':latest.dispatch_state,'output_asset':str(latest.output_asset_id),
                    'output_caption_present':latest.output_caption is not None,
                    'stored_output':await store.load(latest.result_key,latest.result_sha256) is not None if latest.result_key else False}})
        return result


async def preserved_original(db,runner,executor,run_id,stage,page_id=None):
    """Execute one real original attempt, leaving its durable result unsettled."""
    from datetime import timedelta
    from backend.worker.runner import utcnow
    from backend.generation.repository import claim_task
    async with db() as s,s.begin():
        tasks=(await s.scalars(select(Task).where(Task.run_id==run_id))).all()
        chosen=next(t for t in tasks if t.stage==stage and t.status=='queued' and (page_id is None or t.page_id==page_id))
        saved_dates={t.id:t.next_retry_at for t in tasks}
        for task in tasks:
            if task.status=='queued' and task.id!=chosen.id:task.next_retry_at=utcnow()+timedelta(hours=1)
    async with db() as s:claim=await claim_task(s,utcnow(),90)
    assert claim and claim.task_id==chosen.id
    attempt_id,actual_stage,needs_ai=await runner.prepare(claim)
    assert needs_ai and await runner._mark_sent(claim,attempt_id)
    result=await executor.execute(attempt_id,actual_stage)
    async with db() as s,s.begin():
        for task in (await s.scalars(select(Task).where(Task.run_id==run_id))).all():task.next_retry_at=saved_dates[task.id]
    return claim,attempt_id,result


@pytest.mark.asyncio
@pytest.mark.parametrize('stage',['image_transform','caption'])
@pytest.mark.parametrize('deferred_status',['queued','retry_wait'])
async def test_recovered_unknown_exposes_unsent_ai_to_explicit_resume(client,db,tmp_path,monkeypatch,stage,deferred_status):
    from collections import Counter
    from backend.generation.repository import settle_task
    from backend.worker.runner import utcnow
    me,album,run_id,store,executor,runner=await pipeline(client,db,tmp_path)
    calls=[];execute=executor.execute
    async def count_real_execution(attempt_id,actual_stage):
        calls.append((attempt_id,actual_stage))
        return await execute(attempt_id,actual_stage)
    monkeypatch.setattr(executor,'execute',count_real_execution)
    claim,attempt_id,result=await preserved_original(db,runner,executor,run_id,stage)
    async with db() as s,s.begin():
        run=await s.get(Run,run_id);snapshot=run.input_snapshot
        deferred=(await s.scalars(select(Task).where(Task.run_id==run_id,Task.status=='queued',Task.requires_ai_call.is_(True)))).all()
        before={t.id:(t.attempt_count,t.fence_version) for t in deferred}
        for task in deferred:task.status=deferred_status
    async with db() as s:assert await settle_task(s,claim.task_id,claim.fence_version,'unknown',utcnow())
    assert await runner.recover()==1
    async with db() as s:
        assert (await s.get(Run,run_id)).input_snapshot==snapshot
        assert (await s.get(Task,claim.task_id)).status=='succeeded'
        assert (await s.get(Task,claim.task_id)).attempt_count==1
        for task_id,counters in before.items():
            task=await s.get(Task,task_id)
            assert (task.status,task.safe_to_retry,task.error_code)==('failed',True,'AI_TEMPORARY_FAILURE')
            assert (task.attempt_count,task.fence_version)==counters
    view=(await client.get(f'/api/v1/albums/{album}/generation')).json()['data']
    assert view['unknown_pages']==0 and view['can_resume']
    await drain(runner)  # Local work may finish; no new AI before explicit resume.
    assert sum(actual_stage in {'caption','image_transform'} for _,actual_stage in calls)==1
    async with db() as s:
        assert await s.scalar(select(func.count()).select_from(Attempt).join(Task).where(Task.requires_ai_call.is_(True)))==1
        version=(await s.get(Album,UUID(album))).version
    assert (await resume(client,me,album,str(run_id),version)).status_code==202
    await drain(runner)
    async with db() as s:
        assert (await s.get(Run,run_id)).status=='succeeded'
        assert (await s.get(Album,UUID(album))).status=='review_ready'
        assert all(t.attempt_count==1 for t in (await s.scalars(select(Task).where(Task.run_id==run_id,Task.requires_ai_call.is_(True)))).all())
        original=await s.get(Attempt,attempt_id)
        assert original.attempt_no==1 and await runner.store.load(original.result_key)==result
    assert sorted(Counter(call_id for call_id,actual_stage in calls if actual_stage in {'caption','image_transform'}).values())==[1,1,1]


@pytest.mark.asyncio
async def test_only_last_unknown_recovery_exposes_deferred_ai(client,db,tmp_path):
    from backend.generation.repository import settle_task
    from backend.worker.runner import utcnow
    me,album,run_id,store,executor,runner=await pipeline(client,db,tmp_path)
    first=await preserved_original(db,runner,executor,run_id,'image_transform')
    second=await preserved_original(db,runner,executor,run_id,'caption')
    runner.store._path(str(second[1])).unlink()  # Caption response not recovered yet.
    for claim,_,_ in (first,second):
        async with db() as s:assert await settle_task(s,claim.task_id,claim.fence_version,'unknown',utcnow())
    assert await runner.recover()==1
    async with db() as s:
        pending=(await s.scalars(select(Task).where(Task.run_id==run_id,Task.status=='queued',Task.requires_ai_call.is_(True)))).all()
        assert pending and all(not t.safe_to_retry and t.attempt_count==0 for t in pending)
    view=(await client.get(f'/api/v1/albums/{album}/generation')).json()['data']
    assert view['unknown_pages']>0 and not view['can_resume']
    await runner.store.save(str(second[1]),second[2])
    assert await runner.recover()==1
    view=(await client.get(f'/api/v1/albums/{album}/generation')).json()['data']
    assert view['unknown_pages']==0 and view['can_resume']


@pytest.mark.asyncio
async def test_two_connections_recover_last_unknowns_and_classify_once(client,db,tmp_path):
    from backend.generation.repository import settle_task
    from backend.worker.runner import Runner,utcnow
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from sqlalchemy import text
    me,album,run_id,store,executor,runner=await pipeline(client,db,tmp_path)
    originals=[await preserved_original(db,runner,executor,run_id,'image_transform'),
               await preserved_original(db,runner,executor,run_id,'caption')]
    for claim,_,_ in originals:
        async with db() as s:assert await settle_task(s,claim.task_id,claim.fence_version,'unknown',utcnow())
    barrier=asyncio.Barrier(2)
    async def recover_connection():
        async with db.kw['bind'].connect() as conn:
            pid=await conn.scalar(text('SELECT pg_backend_pid()'));await conn.rollback()
            sessions=async_sessionmaker(conn,expire_on_commit=False)
            await barrier.wait()
            return pid,await Runner(sessions,runner.store,executor,lease_seconds=90,heartbeat_seconds=15).recover()
    recovered=await asyncio.wait_for(asyncio.gather(recover_connection(),recover_connection()),15)
    assert recovered[0][0]!=recovered[1][0] and sum(r[1] for r in recovered)==2
    view=(await client.get(f'/api/v1/albums/{album}/generation')).json()['data']
    assert view['unknown_pages']==0 and view['can_resume']


@pytest.mark.asyncio
async def test_worker_drain_recovers_expired_received_result_without_second_call(client,db,tmp_path,monkeypatch):
    from datetime import timedelta
    from backend.worker.runner import utcnow
    me,album,run_id,store,executor,runner=await pipeline(client,db,tmp_path,count=1)
    original_receive=runner._received
    expired=[]
    async with db() as s,s.begin():
        (await s.scalar(select(Task).where(Task.run_id==run_id,Task.stage=='optimize'))).next_retry_at=utcnow()+timedelta(hours=1)
    async def expire_before_receive(claim,*args):
        if not expired:
            async with db() as s,s.begin():
                task=await s.get(Task,claim.task_id)
                assert task.stage=='caption'
                task.lease_until=utcnow()-timedelta(seconds=1)
                (await s.scalar(select(Task).where(Task.run_id==run_id,Task.stage=='optimize'))).next_retry_at=None
            expired.append(claim.task_id)
        return await original_receive(claim,*args)
    monkeypatch.setattr(runner,'_received',expire_before_receive)
    await drain_worker(runner)
    evidence=await pipeline_diagnostics(db,run_id,runner.store)
    print('CONTROLLED_LEASE_EXPIRY',evidence)
    assert evidence['run_status']=='succeeded'
    async with db() as s:
        assert all(t.attempt_count==1 for t in (await s.scalars(select(Task).where(Task.run_id==run_id,Task.requires_ai_call.is_(True)))).all())


@pytest.mark.asyncio
async def test_late_live_result_preserves_running_attempt_and_exposes_only_unsent(client,db,tmp_path):
    from backend.generation.repository import settle_task
    from backend.worker.runner import utcnow
    me,album,run_id,store,executor,runner=await pipeline(client,db,tmp_path)
    first=await preserved_original(db,runner,executor,run_id,'image_transform')
    live=await preserved_original(db,runner,executor,run_id,'caption')
    async with db() as s:assert await settle_task(s,first[0].task_id,first[0].fence_version,'unknown',utcnow())
    assert await runner.recover()==1
    async with db() as s:
        task=await s.get(Task,live[0].task_id)
        assert task.status=='running' and not task.safe_to_retry and task.attempt_count==1
    checksum=await runner.store.save(str(live[1]),live[2])
    assert await runner._received(live[0],live[1],live[2],checksum)
    async with db() as s:assert await settle_task(s,live[0].task_id,live[0].fence_version,'succeeded',utcnow())
    await drain(runner)
    async with db() as s:version=(await s.get(Album,UUID(album))).version
    assert (await resume(client,me,album,str(run_id),version)).status_code==202
    await drain(runner)
    async with db() as s:
        assert (await s.get(Run,run_id)).status=='succeeded'
        assert all(t.attempt_count==1 for t in (await s.scalars(select(Task).where(Task.run_id==run_id,Task.requires_ai_call.is_(True)))).all())


@pytest.mark.asyncio
async def test_unknown_recovery_and_delete_never_reopen_resumable_work(client,db,tmp_path):
    from backend.generation.repository import settle_task
    from backend.worker.runner import utcnow
    me,album,run_id,store,executor,runner=await pipeline(client,db,tmp_path)
    claim,attempt_id,result=await preserved_original(db,runner,executor,run_id,'image_transform')
    async with db() as s:assert await settle_task(s,claim.task_id,claim.fence_version,'unknown',utcnow())
    async with db() as s:version=(await s.get(Album,UUID(album))).version
    recovered,deleted=await asyncio.gather(runner.recover(),client.delete(f'/api/v1/albums/{album}?expected_version={version}',headers=headers(me)))
    assert deleted.status_code==202
    await runner.recover()
    async with db() as s:
        assert (await s.get(Run,run_id)).status=='cancelled'
        assert (await s.get(Album,UUID(album))).status=='deleted'
        assert not any(t.status in {'queued','retry_wait','failed','unknown'} for t in (await s.scalars(select(Task).where(Task.run_id==run_id))).all())
    assert (await client.get(f'/api/v1/albums/{album}/generation')).status_code==404


@pytest.mark.asyncio
@pytest.mark.parametrize('boundary',['prepare','mark_sent'])
async def test_unsent_claim_deferred_after_last_unknown_is_resumable(client,db,tmp_path,boundary):
    from datetime import timedelta
    from backend.generation.repository import claim_task,settle_task
    from backend.worker.runner import utcnow
    me,album,run_id,store,executor,runner=await pipeline(client,db,tmp_path)
    original=await preserved_original(db,runner,executor,run_id,'image_transform')
    async with db() as s,s.begin():
        candidate=await s.scalar(select(Task).where(Task.run_id==run_id,Task.stage=='caption').order_by(Task.id))
        for task in (await s.scalars(select(Task).where(Task.run_id==run_id))).all():
            if task.status=='queued' and task.id!=candidate.id:task.next_retry_at=utcnow()+timedelta(hours=1)
    async with db() as s:claim=await claim_task(s,utcnow(),90)
    assert claim.task_id==candidate.id
    prepared=await runner.prepare(claim) if boundary=='mark_sent' else None
    async with db() as s:assert await settle_task(s,original[0].task_id,original[0].fence_version,'unknown',utcnow())
    assert await runner.recover()==1
    async with db() as s:assert (await s.get(Task,claim.task_id)).status=='running'
    if boundary=='prepare':assert await runner.prepare(claim) is None
    else:assert not await runner._mark_sent(claim,prepared[0])
    async with db() as s:
        task=await s.get(Task,claim.task_id)
        assert (task.status,task.safe_to_retry)==('failed',True)
        assert task.fence_version==claim.fence_version and task.attempt_count==(1 if prepared else 0)
        attempts=(await s.scalars(select(Attempt).where(Attempt.task_id==task.id))).all()
        assert all(a.dispatch_state=='not_sent' for a in attempts)


@pytest.mark.asyncio
async def test_classified_deferred_ai_still_obeys_frozen_attempt_budget(client,db,tmp_path):
    from backend.generation.repository import settle_task
    from backend.worker.runner import utcnow
    me,album,run_id,store,executor,runner=await pipeline(client,db,tmp_path)
    claim,_,_=await preserved_original(db,runner,executor,run_id,'image_transform')
    async with db() as s,s.begin():
        # Simulate a consumed execution budget without changing the frozen config.
        local=await s.scalar(select(Task).where(Task.run_id==run_id,Task.stage=='optimize').order_by(Task.id))
        local.status='failed';local.safe_to_retry=True;local.attempt_count=449
        config_before=(await s.get(Run,run_id)).config_snapshot
    async with db() as s:assert await settle_task(s,claim.task_id,claim.fence_version,'unknown',utcnow())
    assert await runner.recover()==1
    view=(await client.get(f'/api/v1/albums/{album}/generation')).json()['data']
    assert not view['can_resume']
    async with db() as s:
        assert (await s.get(Run,run_id)).config_snapshot==config_before
        version=(await s.get(Album,UUID(album))).version
        deferred=(await s.scalars(select(Task).where(Task.run_id==run_id,Task.stage=='caption'))).all()
        assert all(t.status=='failed' and t.safe_to_retry and t.attempt_count==0 for t in deferred)
    response=await resume(client,me,album,str(run_id),version)
    assert response.status_code==429 and response.json()['error']['code']=='USAGE_LIMIT_EXCEEDED'


@pytest.mark.asyncio
async def test_portrait_landscape_inputs_preserved_and_atomic_completion(client,db,tmp_path):
    me,album,run_id,store,executor,runner=await pipeline(client,db,tmp_path)
    async with db() as s:
        originals={a.id:store.path(a.storage_key).read_bytes() for a in (await s.scalars(select(MediaAsset))).all()}
    await drain(runner)
    async with db() as s:
        run=await s.get(Run,run_id);a=await s.get(Album,UUID(album))
        assert run.status=='succeeded' and a.status=='review_ready'
        assert run.finished_at is not None and run.started_at is not None
        tasks=(await s.scalars(select(Task).where(Task.run_id==run_id))).all()
        assert len(tasks)==6 and all(t.status=='succeeded' for t in tasks)
        image_calls=await s.scalar(select(func.count()).select_from(Attempt).join(Task).where(Task.stage=='image_transform'))
        assert image_calls==1
        for page in (await s.scalars(select(Page).order_by(Page.position))).all():
            assert page.ai_caption==page.caption_text=='함께한 순간이 오래도록 마음에 남아요.'
            for role in ['result','thumbnail']:
                asset=await s.get(MediaAsset,getattr(page,role+'_asset_id'))
                assert asset.status=='ready' and asset.mime=='image/webp'
                with Image.open(store.path(asset.storage_key)) as image:
                    assert image.format=='WEBP' and image.width*4==image.height*3
                assert hashlib.sha256(store.path(asset.storage_key).read_bytes()).hexdigest()==asset.sha256
            if not page.input_is_3_4:
                image=next(t for t in tasks if t.page_id==page.id and t.stage=='image_transform')
                intermediate=await s.get(MediaAsset,image.output_asset_id)
                assert intermediate.role=='transform_output'
                assert (await client.post(f'/api/v1/albums/{album}/media-access',json={'asset_ids':[str(intermediate.id)]},headers=headers(me))).status_code==404
        for asset_id,data in originals.items():
            assert store.path((await s.get(MediaAsset,asset_id)).storage_key).read_bytes()==data
    view=(await client.get(f'/api/v1/albums/{album}/generation')).json()['data']
    assert view['completed_pages']==2 and view['progress_percent']==100 and view['poll_after_ms'] is None


@pytest.mark.asyncio
async def test_corrupt_normalized_input_fails_without_result(client,db,tmp_path):
    me,album,run_id,store,executor,runner=await pipeline(client,db,tmp_path,count=1)
    async with db() as s:
        asset=await s.scalar(select(MediaAsset).where(MediaAsset.role=='normalized'))
    store.path(asset.storage_key).write_bytes(b'corrupt')
    await drain(runner)
    async with db() as s:
        assert (await s.get(Run,run_id)).status=='action_required'
        page=await s.scalar(select(Page));assert page.caption_text is None and page.result_asset_id is None
        assert await s.scalar(select(func.count()).select_from(MediaAsset).where(MediaAsset.role=='result'))==0


@pytest.mark.asyncio
async def test_optimize_storage_failure_resume_never_repeats_image(client,db,tmp_path,monkeypatch):
    me,album,run_id,store,executor,runner=await pipeline(client,db,tmp_path)
    async with db() as s:
        landscape=await s.scalar(select(Page).where(Page.input_is_3_4.is_(False)))
        failure_page=str(landscape.id)
    write=store.write;blocked=True
    def fail_once(key,data):
        if blocked and key.endswith('/'+failure_page+'/result_thumbnail'):raise OSError('injected disk failure')
        return write(key,data)
    monkeypatch.setattr(store,'write',fail_once)
    await drain(runner)
    async with db() as s:
        a=await s.get(Album,UUID(album));version=a.version
        assert a.status=='action_required'
        image_calls=await s.scalar(select(func.count()).select_from(Attempt).join(Task).where(Task.stage=='image_transform'))
        image_before={t.id:t.attempt_count for t in (await s.scalars(select(Task).where(Task.stage=='image_transform'))).all()}
        assert sorted(image_before.values())==[0,1]
        assert all(t.status=='succeeded' for t in (await s.scalars(select(Task).where(Task.stage=='image_transform'))).all())
        failed=(await s.scalars(select(Task).where(Task.stage=='optimize',Task.status=='failed'))).all()
        assert failed and all(t.safe_to_retry and not t.requires_ai_call for t in failed)
    blocked=False
    r=await resume(client,me,album,str(run_id),version);assert r.status_code==202
    await drain(runner)
    async with db() as s:
        assert (await s.get(Album,UUID(album))).status=='review_ready'
        assert await s.scalar(select(func.count()).select_from(Attempt).join(Task).where(Task.stage=='image_transform'))==image_calls
        assert {t.id:t.attempt_count for t in (await s.scalars(select(Task).where(Task.stage=='image_transform'))).all()}==image_before


@pytest.mark.asyncio
@pytest.mark.parametrize('phase',['sent','saved','image_saved','image_corrupt'])
async def test_forced_crash_restart_original_only(client,db,tmp_path,phase):
    import os,sys
    from datetime import datetime,timezone,timedelta
    from backend.worker.runner import ResultStore
    me,album,run_id,store,executor,runner=await pipeline(client,db,tmp_path)
    async with db() as s,s.begin():
        tasks=(await s.scalars(select(Task).where(Task.run_id==run_id))).all()
        chosen=next(t for t in tasks if t.stage==('image_transform' if phase in {'image_saved','image_corrupt'} else 'caption') and t.status=='queued')
        chosen_id=chosen.id
        for t in tasks:
            if t.id!=chosen_id and t.status=='queued':t.status='failed';t.safe_to_retry=True
    process=await asyncio.create_subprocess_exec(sys.executable,'-m','backend.tests.integration.test_generation_pipeline','image_saved' if phase=='image_corrupt' else phase,str(store.root),stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
    try:
        async with asyncio.timeout(15):
            while not (store.root/'barrier').exists():
                assert process.returncode is None
                await asyncio.sleep(.02)
        process.kill();await process.wait()
    finally:
        if process.returncode is None:process.kill();await process.wait()
    async with db() as s,s.begin():
        (await s.get(Task,chosen_id)).lease_until=datetime.now(timezone.utc)-timedelta(seconds=1)
    if phase in {'image_saved','image_corrupt'}:
        async with db() as s:
            original=await s.scalar(select(Attempt).where(Attempt.task_id==chosen_id))
            assert original.output_asset_id is not None
    if phase=='image_corrupt':
        for path in store.root.rglob('transform_output'):
            Image.new('RGB',(60,80),'blue').save(path,format='WEBP',lossless=True)
    await runner.recover()
    async with db() as s:
        task=await s.get(Task,chosen_id)
        assert task.status==('unknown' if phase in {'sent','image_corrupt'} else 'succeeded')
        attempt=await s.scalar(select(Attempt).where(Attempt.task_id==chosen_id))
        attempt_id=attempt.id
    calls=(store.root/'calls').read_text()
    if phase=='sent':
        for _ in range(3):await runner.recover()
        async with db() as s:assert (await s.get(Task,chosen_id)).status=='unknown'
        assert (store.root/'calls').read_text()==calls
        await runner.store.save(str(attempt_id),{'caption':'함께한 순간이 오래도록 마음에 남아요.'})
        assert await runner.recover()==1
        async with db() as s:
            assert (await s.get(Task,chosen_id)).status=='succeeded'
            version=(await s.get(Album,UUID(album))).version
        assert (await resume(client,me,album,str(run_id),version)).status_code==202
        await drain(runner)
        async with db() as s:assert (await s.get(Run,run_id)).status=='succeeded'
    assert (store.root/'calls').read_text()==calls and calls.count('\n')==1


@pytest.mark.asyncio
async def test_generation_heartbeat_and_cancel_work(client,db,tmp_path):
    from backend.worker.runner import Runner
    from datetime import datetime,timezone
    me,album,run_id,store,executor,runner=await pipeline(client,db,tmp_path,count=1)
    started=asyncio.Event();cancelled=asyncio.Event()
    class Waiting:
        async def execute(self,*args):
            started.set()
            try:await asyncio.Event().wait()
            finally:cancelled.set()
    runner.adapter=runner.local_executor=Waiting()
    work=asyncio.create_task(runner.run_once())
    await asyncio.wait_for(started.wait(),5)
    async with db() as s:
        task=await s.scalar(select(Task).where(Task.status=='running'));original=task.lease_until;task_id=task.id
    async with asyncio.timeout(5):
        while True:
            async with db() as s:
                if (await s.get(Task,task_id)).lease_until>original:break
            assert (await client.get(f'/api/v1/albums/{album}/generation')).status_code==200
            await asyncio.sleep(.03)
    work.cancel()
    with pytest.raises(asyncio.CancelledError):await work
    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_result_thumbnails_private_and_deleted_sweep_cleans_both(client,db,tmp_path):
    from backend.storage.local import storage_key
    from backend.uploads.validation import ValidationWorker
    me,album,run_id,store,executor,runner=await pipeline(client,db,tmp_path)
    async with db() as s,s.begin():
        for page in (await s.scalars(select(Page))).all():
            a=await s.get(Album,page.album_id)
            key=storage_key(a.owner_id,a.id,page.id,'thumbnail')
            out=BytesIO();Image.new('RGB',(15,20),'blue').save(out,format='WEBP',lossless=True);data=out.getvalue()
            from uuid import uuid5,NAMESPACE_URL
            asset=MediaAsset(id=uuid5(NAMESPACE_URL,key),owner_id=a.owner_id,album_id=a.id,page_id=page.id,role='thumbnail',storage_key=key,mime='image/webp',bytes=len(data),sha256=hashlib.sha256(data).hexdigest(),width=15,height=20,status='ready')
            s.add(asset);await s.flush();page.thumbnail_asset_id=asset.id;store.write(key,data)
    drafts={p: p.read_bytes() for p in store.root.rglob('thumbnail')}
    await drain(runner)
    async with db() as s:
        a=await s.get(Album,UUID(album));version=a.version
        page=await s.scalar(select(Page).order_by(Page.position))
        thumb=await s.get(MediaAsset,page.thumbnail_asset_id)
        assert thumb.storage_key.endswith('/result_thumbnail') and thumb.role=='thumbnail'
    access=await client.post(f'/api/v1/albums/{album}/media-access',json={'asset_ids':[str(thumb.id)]},headers=headers(me))
    assert access.status_code==200
    assert (await client.get(access.json()['data']['media_access'][0]['url'])).status_code==200
    assert all(p.read_bytes()==data for p,data in drafts.items())
    assert (await client.delete(f'/api/v1/albums/{album}?expected_version={version}',headers=headers(me))).status_code==202
    await runner.maintenance()
    validation=ValidationWorker(db,config(storage_root=store.root))
    while await validation.run_once():pass
    assert not list(store.root.rglob('result_thumbnail')) and not list(store.root.rglob('transform_output'))
    assert not any(p.exists() for p in drafts)


@pytest.mark.asyncio
@pytest.mark.parametrize('count',[1,50])
async def test_small_synthetic_single_worker_load(client,db,tmp_path,count):
    import time,resource
    me,album,run_id,store,executor,runner=await pipeline(client,db,tmp_path,count=count,production_schedule=True)
    before=time.monotonic()
    await drain_worker(runner,limit=151)
    async with db() as s:
        status=(await s.get(Run,run_id)).status
        if status!='succeeded':
            print('PIPELINE_FAILURE',await pipeline_diagnostics(db,run_id,runner.store))
        assert status=='succeeded'
        assert await s.scalar(select(func.count()).select_from(Task).where(Task.status=='succeeded'))==count*3
    print({'photos':count,'elapsed_seconds':round(time.monotonic()-before,3),'parent_maxrss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'sizes':'30x40/60x20 synthetic WebP','workers':1})


async def _crash_main(phase,root):
    import os,time
    from pathlib import Path
    from backend.database import session_factory
    from backend.storage.local import LocalStorage
    from backend.generation.fake_adapter import FakeExecutor
    from backend.worker.runner import Runner,ResultStore
    db=session_factory();store=LocalStorage(root)
    if phase=='entrypoint':
        import sys
        from backend.generation import fake_adapter
        from backend.media.process import _run_child
        async def slow_image(*args,**kwargs):
            marker=root/'child_pid'
            await _run_child([sys.executable,'-c',
                'import os,time,pathlib; marker=pathlib.Path('+repr(str(marker))+'); '
                'pending=marker.with_name(marker.name+".tmp"); pending.write_text(str(os.getpid())); '
                'pending.replace(marker); time.sleep(30)'],120)
        fake_adapter.fake_transform=slow_image
        os.environ.update(APP_ENV='local',DEV_AI_ENABLED='true',STORAGE_ROOT=str(root),WORKER_POLL_SECONDS='.01')
        from backend.worker.__main__ import main
        await main()
        return
    class Counting(FakeExecutor):
        async def execute(self,*args):
            with (root/'calls').open('a') as f:f.write('call\n');f.flush();os.fsync(f.fileno())
            if phase=='sent':
                (root/'barrier').touch()
                await asyncio.Event().wait()
            return await super().execute(*args)
    class BlockingResult(ResultStore):
        async def save(self,*args):
            result=await super().save(*args)
            if phase=='saved':
                (root/'barrier').touch();await asyncio.Event().wait()
            return result
    write=store.write
    if phase=='image_saved':
        def blocked(key,data):
            write(key,data)
            if key.endswith('/transform_output'):
                (root/'barrier').touch()
                while True:time.sleep(.02)
        store.write=blocked
    adapter=Counting(db,store)
    await Runner(db,BlockingResult(root),adapter,local_executor=adapter).run_once()


if __name__=='__main__':
    import sys
    from pathlib import Path
    asyncio.run(_crash_main(sys.argv[1],Path(sys.argv[2])))


@pytest.mark.asyncio
async def test_late_last_result_deleted_and_edited_caption_never_overwritten(client,db,tmp_path):
    from datetime import datetime,timezone
    me,album,run_id,store,executor,runner=await pipeline(client,db,tmp_path,count=1)
    async with db() as s,s.begin():
        page=await s.scalar(select(Page));page.caption_text='사용자가 저장한 글귀';page.caption_edited_at=datetime.now(timezone.utc)
    receive=runner._received;deleted=False
    async def delete_before_last_settle(*args):
        nonlocal deleted
        accepted=await receive(*args)
        async with db() as s:
            pending=await s.scalar(select(func.count()).select_from(Task).where(Task.run_id==run_id,Task.status!='succeeded'))
            version=(await s.get(Album,UUID(album))).version
        if accepted and pending==1:
            r=await client.delete(f'/api/v1/albums/{album}?expected_version={version}',headers=headers(me))
            assert r.status_code==202;deleted=True
        return accepted
    runner._received=delete_before_last_settle
    await drain(runner)
    assert deleted
    async with db() as s:
        assert (await s.get(Run,run_id)).status=='cancelled'
        assert (await s.get(Album,UUID(album))).status=='deleted'
        page=await s.scalar(select(Page));assert page.caption_text=='사용자가 저장한 글귀'
    assert (await client.get(f'/api/v1/albums/{album}/generation')).status_code==404


@pytest.mark.asyncio
async def test_stage_invalid_output_fails_closed_and_preserves_envelope(client,db,tmp_path):
    me,album,run_id,store,executor,runner=await pipeline(client,db,tmp_path,count=1)
    async with db() as s,s.begin():
        source=await s.scalar(select(MediaAsset).where(MediaAsset.role=='source'))
        source_id=source.id
        tasks=(await s.scalars(select(Task).where(Task.run_id==run_id))).all()
        image=next(t for t in tasks if t.stage=='image_transform');image.status='queued';image.requires_ai_call=True
        image.completion_kind=None;image.output_asset_id=None;image_id=image.id
        for t in tasks:
            if t.id!=image_id:t.status='failed'
    class Invalid:
        async def execute(self,*args):return {'asset_id':str(source_id)}
    runner.adapter=Invalid()
    assert await runner.run_once()
    async with db() as s:
        task=await s.get(Task,image_id)
        assert task.status=='failed' and task.error_code=='MEDIA_SAVE_FAILED' and not task.safe_to_retry
        assert (await s.get(Run,run_id)).status=='action_required'
        attempt=await s.scalar(select(Attempt).where(Attempt.task_id==image_id))
        assert await runner.store.load(str(attempt.id))=={'asset_id':str(source_id)}


@pytest.mark.asyncio
async def test_worker_prepare_enforces_frozen_run_budget(client,db,tmp_path):
    me,album,run_id,store,executor,runner=await pipeline(client,db,tmp_path,count=1)
    async with db() as s,s.begin():
        task=await s.scalar(select(Task).where(Task.stage=='caption'));task.attempt_count=450
    await runner.run_once()
    async with db() as s:
        assert await s.scalar(select(func.count()).select_from(Attempt))==0
        assert (await s.get(Run,run_id)).status=='action_required'


@pytest.mark.asyncio
async def test_real_entrypoint_sigterm_cancels_and_reaps_media_child(client,db,tmp_path):
    import os,sys
    me,album,run_id,store,executor,runner=await pipeline(client,db,tmp_path)
    async with db() as s,s.begin():
        tasks=(await s.scalars(select(Task).where(Task.run_id==run_id))).all()
        for task in tasks:
            if task.stage!='image_transform' and task.status=='queued':task.status='failed'
    process=await asyncio.create_subprocess_exec(sys.executable,'-m','backend.tests.integration.test_generation_pipeline','entrypoint',str(store.root),stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
    try:
        async with asyncio.timeout(15):
            while not (store.root/'child_pid').exists():
                assert process.returncode is None
                await asyncio.sleep(.02)
        pid=int((store.root/'child_pid').read_text())
        process.terminate()
        async with asyncio.timeout(5):await process.communicate()
        assert process.returncode==0
        with pytest.raises(ProcessLookupError):os.kill(pid,0)
    finally:
        if process.returncode is None:process.kill();await process.wait()


@pytest.mark.asyncio
async def test_portrait_optimize_failure_defers_first_landscape_call_until_resume(client,db,tmp_path,monkeypatch):
    from datetime import datetime,timezone,timedelta
    me,album,run_id,store,executor,runner=await pipeline(client,db,tmp_path)
    async with db() as s,s.begin():
        portrait=await s.scalar(select(Page).where(Page.input_is_3_4.is_(True)))
        tasks=(await s.scalars(select(Task).where(Task.run_id==run_id))).all()
        image=next(t for t in tasks if t.stage=='image_transform' and t.status=='queued');image_id=image.id
        for task in tasks:
            if task.status=='queued' and not (task.page_id==portrait.id and task.stage=='optimize'):
                task.next_retry_at=datetime.now(timezone.utc)+timedelta(hours=1)
    write=store.write
    def broken(key,data):
        if key.endswith('/result_thumbnail'):raise OSError('injected disk failure before landscape starts')
        return write(key,data)
    monkeypatch.setattr(store,'write',broken)
    assert await runner.run_once()
    async with db() as s:
        image=await s.get(Task,image_id)
        assert image.status=='queued' and image.attempt_count==0
        version=(await s.get(Album,UUID(album))).version
    assert not await runner.run_once()
    monkeypatch.setattr(store,'write',write)
    assert (await resume(client,me,album,str(run_id),version)).status_code==202
    async with db() as s,s.begin():
        for task in (await s.scalars(select(Task).where(Task.run_id==run_id))).all():task.next_retry_at=None
    await drain(runner)
    async with db() as s:
        assert (await s.get(Task,image_id)).attempt_count==1
        assert (await s.get(Run,run_id)).status=='succeeded'


@pytest.mark.asyncio
async def test_two_connections_last_caption_and_optimize_complete_once(client,db,tmp_path):
    from backend.generation.repository import claim_task,settle_task
    from backend.worker.runner import utcnow
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy import text
    me,album,run_id,store,executor,runner=await pipeline(client,db,tmp_path,count=1)
    claims=[]
    for _ in range(2):
        async with db() as s:claim=await claim_task(s,utcnow(),90)
        attempt_id,stage,needs_ai=await runner.prepare(claim)
        if needs_ai:assert await runner._mark_sent(claim,attempt_id)
        result=await executor.execute(attempt_id,stage)
        checksum=await runner.store.save(str(attempt_id),result)
        assert await runner._received(claim,attempt_id,result,checksum)
        claims.append(claim)
    barrier=asyncio.Barrier(2)
    async def finish(claim):
        async with db.kw['bind'].connect() as connection:
            pid=await connection.scalar(text('SELECT pg_backend_pid()'));await connection.rollback()
            await barrier.wait()
            async with AsyncSession(bind=connection,expire_on_commit=False) as s:
                return pid,await settle_task(s,claim.task_id,claim.fence_version,'succeeded',utcnow())
    results=await asyncio.wait_for(asyncio.gather(*(finish(c) for c in claims)),10)
    assert results[0][0]!=results[1][0] and all(r[1] for r in results)
    async with db() as s:
        a=await s.get(Album,UUID(album));run=await s.get(Run,run_id)
        assert a.status=='review_ready' and a.version==5 and run.status=='succeeded'
        assert (await s.scalar(select(Page))).version==3
