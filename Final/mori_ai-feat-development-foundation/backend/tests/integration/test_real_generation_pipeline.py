"""Real executor/ledger over PostgreSQL and durable media; provider is always mocked."""
import asyncio
from datetime import timedelta
from decimal import Decimal
from io import BytesIO
from types import SimpleNamespace
from uuid import UUID
import pytest
from PIL import Image
from sqlalchemy import select, text
from backend.models import Album, Run, Task, Attempt, Page, AIBudgetEntry
from backend.tests.integration.test_generation_pipeline import client, pipeline, drain
from backend.worker.runner import Runner, utcnow
from backend.generation.service import config_snapshot
from backend.generation.repository import claim_task


class Provider:
    def __init__(self):
        self.calls=[]
        self.failure=None
        self.callback=None

    async def respond(self,stage,image):
        from backend.generation.openai_provider import ProviderResult
        self.calls.append((stage,image))
        if self.callback: await self.callback()
        if self.failure: raise self.failure
        output=BytesIO();Image.new('RGB',(768,1024),'blue').save(output,format='WEBP')
        return ProviderResult(caption='빛나는 순간이 남아요.',image=output.getvalue(),
            cost_usd=Decimal('.001'),usage={'input_tokens':10},request_id='req_test')

    async def caption(self,image,*,prompt_version='openai-memory-v2'):
        self.prompt_version=prompt_version
        return await self.respond('caption',image)
    async def transform(self,image):return await self.respond('image_transform',image)


async def real_pipeline(client,db,tmp_path,count=2,limit=Decimal('5')):
    from backend.generation.real_adapter import RealExecutor
    from backend.generation.budget import BudgetLedger
    from backend.tests.integration.test_auth_http import config
    me,album,run_id,store,_,_=await pipeline(client,db,tmp_path,count=count)
    settings=config().model_copy(update={'ai_real_calls_enabled':True,
        'openai_caption_model':'gpt-5.4-mini','openai_image_model':'gpt-image-2'})
    async with db() as s,s.begin():
        # Financial rows intentionally do not cascade with user fixtures.
        await s.execute(text('TRUNCATE ai_budget_entries, ai_budget_accounts'))
        run=await s.get(Run,run_id);run.config_snapshot=config_snapshot(settings)
    ledger=BudgetLedger(db,limit,Decimal('100'));provider=Provider()
    executor=RealExecutor(db,store,provider,ledger,settings)
    from backend.storage.factory import result_store
    runner=Runner(db,result_store(store),executor,local_executor=executor)
    return me,album,run_id,store,executor,runner,provider,ledger


async def only_stage(db,run_id,stage):
    async with db() as s,s.begin():
        tasks=(await s.scalars(select(Task).where(Task.run_id==run_id))).all()
        target=next(t for t in tasks if t.stage==stage and t.status=='queued')
        for task in tasks:
            if task.id!=target.id and task.status=='queued':task.next_retry_at=utcnow()+timedelta(hours=1)
        return target.id


@pytest.mark.asyncio
async def test_real_complete_uses_original_caption_and_skips_exact_ratio(client,db,tmp_path):
    _,album,rid,store,executor,runner,provider,ledger=await real_pipeline(client,db,tmp_path)
    await drain(runner)
    assert [s for s,_ in provider.calls].count('image_transform')==1
    assert [s for s,_ in provider.calls].count('caption')==2
    sizes=[]
    for stage,data in provider.calls:
        if stage=='caption':
            with Image.open(BytesIO(data)) as im:sizes.append(im.size)
    assert sorted(sizes)==[(30,40),(60,20)]
    async with db() as s:
        assert (await s.get(Run,rid)).status=='succeeded'
        assert (await s.get(Album,UUID(album))).status=='review_ready'
        assert all(p.result_asset_id and p.thumbnail_asset_id for p in (await s.scalars(select(Page))).all())
    assert (await ledger.summary())['charged_usd']==Decimal('.003')


@pytest.mark.asyncio
@pytest.mark.parametrize('failure',['timeout','invalid','budget','storage'])
async def test_real_failures_do_not_resend_or_lose_charge(client,db,tmp_path,monkeypatch,failure):
    from backend.generation.openai_provider import ProviderFailure,CAPTION_RESERVATION_USD
    args=await real_pipeline(client,db,tmp_path,count=1,limit=Decimal('.00001') if failure=='budget' else Decimal('5'))
    _,_,rid,store,executor,runner,provider,ledger=args
    tid=await only_stage(db,rid,'caption')
    if failure=='timeout':provider.failure=ProviderFailure('AI_PROVIDER_UNKNOWN',dispatch_state='unknown')
    if failure=='invalid':provider.failure=ProviderFailure('AI_CAPTION_INVALID',dispatch_state='responded',cost_usd=Decimal('.002'),usage={'input_tokens':10})
    if failure=='storage':
        from backend.storage.r2 import StorageUnavailable
        def broken(*args):raise StorageUnavailable('unavailable')
        monkeypatch.setattr(store,'read_bytes',broken)
    assert await runner.run_once()
    await runner.recover();await runner.recover()
    async with db() as s:
        task=await s.get(Task,tid)
        assert task.status==('unknown' if failure=='timeout' else 'failed')
        assert task.safe_to_retry==(failure in {'storage','budget'})
    assert len(provider.calls)==(1 if failure in {'timeout','invalid'} else 0)
    assert (await ledger.summary())['charged_usd']==({'timeout':CAPTION_RESERVATION_USD,'invalid':Decimal('.002')}.get(failure,Decimal(0)))


@pytest.mark.asyncio
@pytest.mark.parametrize('stage',['caption','image_transform'])
async def test_saved_original_recovered_without_second_payment(client,db,tmp_path,stage):
    _,_,rid,store,executor,runner,provider,ledger=await real_pipeline(client,db,tmp_path)
    tid=await only_stage(db,rid,stage)
    async with db() as s:claim=await claim_task(s,utcnow(),90)
    aid,actual,_=await runner.prepare(claim)
    await executor.execute(aid,actual)
    async with db() as s,s.begin():(await s.get(Task,tid)).lease_until=utcnow()-timedelta(seconds=1)
    # New runner simulates restart, consuming only original durable output.
    restarted=Runner(db,runner.store,executor,local_executor=executor)
    assert await restarted.recover()==1
    assert len(provider.calls)==1
    assert (await ledger.summary())['charged_usd']==Decimal('.001')


@pytest.mark.asyncio
async def test_duplicate_reserved_attempt_never_dispatches(client,db,tmp_path):
    from backend.generation.openai_provider import CAPTION_RESERVATION_USD
    from backend.generation.real_adapter import RealExecutionError
    _,_,rid,_,executor,runner,provider,ledger=await real_pipeline(client,db,tmp_path,count=1)
    await only_stage(db,rid,'caption')
    async with db() as s:claim=await claim_task(s,utcnow(),90)
    aid,stage,_=await runner.prepare(claim)
    assert await ledger.reserve(aid,CAPTION_RESERVATION_USD)
    with pytest.raises(RealExecutionError):await executor.execute(aid,stage)
    assert provider.calls==[]
    assert (await ledger.summary())['charged_usd']==CAPTION_RESERVATION_USD


@pytest.mark.asyncio
async def test_cancelled_inflight_reservation_survives_restart(client,db,tmp_path):
    from backend.generation.openai_provider import CAPTION_RESERVATION_USD
    _,_,rid,_,executor,runner,provider,ledger=await real_pipeline(client,db,tmp_path,count=1)
    tid=await only_stage(db,rid,'caption');started=asyncio.Event()
    async def wait():started.set();await asyncio.Event().wait()
    provider.callback=wait
    work=asyncio.create_task(runner.run_once());await asyncio.wait_for(started.wait(),5)
    work.cancel()
    with pytest.raises(asyncio.CancelledError):await work
    async with db() as s,s.begin():(await s.get(Task,tid)).lease_until=utcnow()-timedelta(seconds=1)
    await runner.recover();await runner.recover()
    async with db() as s:assert (await s.get(Task,tid)).status=='unknown'
    assert len(provider.calls)==1 and (await ledger.summary())['charged_usd']==CAPTION_RESERVATION_USD


@pytest.mark.asyncio
async def test_deleted_during_response_still_charged(client,db,tmp_path):
    from backend.tests.integration.test_album_http import headers
    me,album,rid,_,executor,runner,provider,ledger=await real_pipeline(client,db,tmp_path)
    await only_stage(db,rid,'image_transform')
    async def delete():
        async with db() as s:version=(await s.get(Album,UUID(album))).version
        response=await client.delete(f'/api/v1/albums/{album}?expected_version={version}',headers=headers(me))
        assert response.status_code==202
    provider.callback=delete
    await runner.run_once();await runner.recover()
    async with db() as s:
        assert (await s.get(Album,UUID(album))).status=='deleted'
        assert all(p.result_asset_id is None for p in (await s.scalars(select(Page))).all())
    assert (await ledger.summary())['charged_usd']==Decimal('.001')


@pytest.mark.asyncio
@pytest.mark.parametrize('kind',['fake','model'])
async def test_mode_and_model_mismatch_cannot_dispatch(client,db,tmp_path,kind):
    _,_,rid,store,executor,runner,provider,ledger=await real_pipeline(client,db,tmp_path,count=1)
    tid=await only_stage(db,rid,'caption')
    if kind=='fake':
        from backend.generation.fake_adapter import FakeExecutor
        runner.adapter=FakeExecutor(db,store)
    else:
        executor.caption_model='unreviewed-model'
    assert not await runner.run_once()
    async with db() as s:
        task=await s.get(Task,tid)
        assert task.status==('queued' if kind=='fake' else 'failed') and task.attempt_count==0
    assert provider.calls==[] and (await ledger.summary())['charged_usd']==0


@pytest.mark.asyncio
@pytest.mark.parametrize('failure',['image','caption'])
async def test_invalid_mock_response_never_publishes_and_keeps_cost(client,db,tmp_path,failure):
    from backend.generation.openai_provider import ProviderResult
    _,_,rid,store,executor,runner,provider,ledger=await real_pipeline(client,db,tmp_path)
    tid=await only_stage(db,rid,'image_transform' if failure=='image' else 'caption')
    async def invalid(data,**kwargs):
        return ProviderResult(caption='x'*81,image=b'not an image',cost_usd=Decimal('.004'))
    provider.transform=provider.caption=invalid
    await runner.run_once()
    async with db() as s:
        task=await s.get(Task,tid)
        assert task.status=='failed' and not task.safe_to_retry
    assert (await ledger.summary())['charged_usd']==Decimal('.004')


@pytest.mark.asyncio
async def test_image_file_saved_before_envelope_recovers_original(client,db,tmp_path,monkeypatch):
    from backend.storage.factory import result_store
    _,_,rid,store,executor,runner,provider,ledger=await real_pipeline(client,db,tmp_path)
    tid=await only_stage(db,rid,'image_transform')
    import backend.generation.real_adapter as module
    class BrokenEnvelope:
        async def save(self,*args):raise OSError('injected post-media crash')
    monkeypatch.setattr(module,'result_store',lambda store:BrokenEnvelope())
    await runner.run_once()
    async with db() as s:assert (await s.get(Task,tid)).status=='unknown'
    monkeypatch.setattr(module,'result_store',result_store)
    assert await runner.recover()==1
    assert len(provider.calls)==1 and (await ledger.summary())['charged_usd']==Decimal('.001')


@pytest.mark.asyncio
async def test_lost_fence_after_response_can_only_recover_original(client,db,tmp_path):
    _,_,rid,store,executor,runner,provider,ledger=await real_pipeline(client,db,tmp_path,count=1)
    tid=await only_stage(db,rid,'caption')
    async def expire():
        async with db() as s,s.begin():
            task=await s.get(Task,tid);task.fence_version+=1;task.lease_until=utcnow()-timedelta(seconds=1)
    provider.callback=expire
    await runner.run_once()
    async with db() as s:assert (await s.get(Task,tid)).status=='running'
    assert await runner.recover()==1
    assert len(provider.calls)==1
    assert (await ledger.summary())['charged_usd']==Decimal('.001')


@pytest.mark.asyncio
@pytest.mark.parametrize('stage',['caption','image_transform'])
async def test_accounting_outage_recovers_saved_result_and_usage(client,db,tmp_path,monkeypatch,stage):
    _,_,rid,store,executor,runner,provider,ledger=await real_pipeline(client,db,tmp_path)
    tid=await only_stage(db,rid,stage)
    original=ledger.settle
    async def unavailable(*args):raise RuntimeError('database unavailable')
    monkeypatch.setattr(ledger,'settle',unavailable)
    await runner.run_once()
    async with db() as s:assert (await s.get(Task,tid)).status=='unknown'
    monkeypatch.setattr(ledger,'settle',original)
    assert await runner.recover()==1
    assert len(provider.calls)==1
    assert (await ledger.summary())['charged_usd']==Decimal('.001')


@pytest.mark.asyncio
async def test_reservation_is_committed_before_provider_dispatch(client,db,tmp_path):
    _,_,rid,_,executor,runner,provider,ledger=await real_pipeline(client,db,tmp_path,count=1)
    tid=await only_stage(db,rid,'caption')
    async def inspect():
        async with db() as s:
            attempt=await s.scalar(select(Attempt).where(Attempt.task_id==tid))
            entry=await s.get(AIBudgetEntry,attempt.id)
            assert entry is not None and entry.status=='reserved'
            assert attempt.dispatch_state=='accepted_or_unknown'
    provider.callback=inspect
    await runner.run_once()
    async with db() as s:assert (await s.get(Task,tid)).status=='succeeded'


@pytest.mark.asyncio
async def test_corrupt_original_is_definitively_unsent(client,db,tmp_path):
    from backend.models import MediaAsset
    _,_,rid,store,executor,runner,provider,ledger=await real_pipeline(client,db,tmp_path,count=1)
    tid=await only_stage(db,rid,'caption')
    async with db() as s:asset=await s.scalar(select(MediaAsset).where(MediaAsset.role=='normalized'))
    store.path(asset.storage_key).write_bytes(b'corrupt')
    await runner.run_once()
    async with db() as s:
        assert (await s.get(Task,tid)).status=='failed'
        assert (await s.scalar(select(Attempt).where(Attempt.task_id==tid))).dispatch_state=='not_sent'
    assert provider.calls==[] and (await ledger.summary())['charged_usd']==0


@pytest.mark.asyncio
@pytest.mark.parametrize('field',['prompt_version','pricing_profile'])
async def test_unreviewed_snapshot_versions_cannot_dispatch(client,db,tmp_path,field):
    _,_,rid,_,executor,runner,provider,ledger=await real_pipeline(client,db,tmp_path,count=1)
    tid=await only_stage(db,rid,'caption')
    async with db() as s,s.begin():
        run=await s.get(Run,rid);run.config_snapshot={**run.config_snapshot,field:'unreviewed'}
    await runner.run_once()
    async with db() as s:
        task=await s.get(Task,tid)
        assert task.status=='failed' and task.attempt_count==0
    assert provider.calls==[] and (await ledger.summary())['charged_usd']==0


@pytest.mark.asyncio
async def test_sibling_unknown_before_dispatch_releases_unsent_and_allows_resume(client,db,tmp_path,monkeypatch):
    from backend.generation.repository import settle_task
    from backend.generation.resume_policy import resume_failed_tasks
    _,_,rid,_,executor,runner,provider,ledger=await real_pipeline(client,db,tmp_path)
    first_tid=await only_stage(db,rid,'image_transform')
    async with db() as s:first_claim=await claim_task(s,utcnow(),90)
    first_aid,stage,_=await runner.prepare(first_claim)
    await executor.execute(first_aid,stage)
    tid=await only_stage(db,rid,'caption')
    async with db() as s,s.begin():(await s.get(Task,tid)).next_retry_at=None
    original=ledger.reserve
    async def pause_after_reserve(aid,amount):
        first=await original(aid,amount)
        async with db() as s:assert await settle_task(s,first_tid,first_claim.fence_version,'unknown',utcnow())
        return first
    monkeypatch.setattr(ledger,'reserve',pause_after_reserve)
    await runner.run_once()
    async with db() as s:
        task=await s.get(Task,tid)
        assert task.status=='failed' and task.safe_to_retry
        attempt=await s.scalar(select(Attempt).where(Attempt.task_id==tid))
        assert attempt.dispatch_state=='not_sent'
        assert (await s.get(AIBudgetEntry,attempt.id)).status=='released'
    assert len(provider.calls)==1
    monkeypatch.setattr(ledger,'reserve',original)
    assert await runner.recover()==1
    async with db() as s:assert tid in await resume_failed_tasks(s,rid)
    assert await runner.run_once()
    assert len(provider.calls)==2


@pytest.mark.asyncio
@pytest.mark.parametrize('version',['openai-v1','openai-memory-v2','openai-memory-v3'])
async def test_caption_dispatch_preserves_frozen_prompt_version(client,db,tmp_path,version):
    _,_,rid,_,executor,runner,provider,ledger=await real_pipeline(client,db,tmp_path,count=1)
    await only_stage(db,rid,'caption')
    async with db() as s,s.begin():
        run=await s.get(Run,rid);run.config_snapshot={**run.config_snapshot,'prompt_version':version}
    assert await runner.run_once()
    assert provider.prompt_version==version
    assert len(provider.calls)==1


@pytest.mark.asyncio
async def test_http_resume_preserves_legacy_prompt_after_default_upgrade(client,db,tmp_path):
    from backend.main import create_app
    from backend.tests.integration.test_auth_http import config
    from backend.tests.integration.test_album_http import headers
    from backend.generation.openai_provider import ProviderFailure
    import httpx
    me,album,rid,store,executor,runner,provider,ledger=await real_pipeline(client,db,tmp_path,count=1)
    tid=await only_stage(db,rid,'caption')
    async with db() as s,s.begin():
        run=await s.get(Run,rid);run.config_snapshot={**run.config_snapshot,'prompt_version':'openai-v1'}
    provider.failure=ProviderFailure('AI_TEMPORARY_FAILURE',safe_to_retry=True,dispatch_state='rejected')
    await runner.run_once()
    async with db() as s:version=(await s.get(Album,UUID(album))).version
    settings=config().model_copy(update={'ai_real_calls_enabled':True,'dev_ai_enabled':False})
    app=create_app(settings=settings,session_factory=db)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url=client.base_url,cookies=client.cookies) as real_client:
            response=await real_client.post(f'/api/v1/albums/{album}/generation/resume',
                json={'run_id':str(rid),'expected_version':version},headers=headers(me,'legacy-resume'))
    assert response.status_code==202,response.text
    provider.failure=None
    assert await runner.run_once(stage='caption')
    assert provider.prompt_version=='openai-v1'
    async with db() as s:assert (await s.get(Task,tid)).status=='succeeded'
