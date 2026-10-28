"""Real PostgreSQL/media processes, injected in-memory S3 only; no R2 calls."""
import asyncio
import hashlib
import io
import json
import shutil
import threading
import time
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, func
from backend.models import Album, Attempt, Job, MediaAsset, Page, Run, Task, Upload
from backend.storage.r2 import R2Storage, StorageUnavailable
from backend.tests.integration.test_generation_pipeline import client, pipeline, preserved_original, drain
from backend.tests.integration.test_validation_worker import pending
from backend.tests.integration.test_auth_http import config
from backend.worker.runner import Runner, utcnow


class S3Error(Exception):
    def __init__(self, status):
        super().__init__('secret URL must not escape')
        self.response={'Error':{'Code':str(status)},'ResponseMetadata':{'HTTPStatusCode':status}}


class FakeS3:
    def __init__(self):
        self.objects={}; self.calls=[]; self.lock=threading.Lock(); self.error=None; self.delay=0
    def check(self, op, kw):
        self.calls.append((op,kw['Key']))
        time.sleep(self.delay)
        if self.error: raise S3Error(self.error)
        assert kw['Bucket']=='r2-worker-test'
    def put_object(self,**kw):
        self.check('put',kw)
        assert kw['IfNoneMatch']=='*'
        with self.lock:
            if kw['Key'] in self.objects: raise S3Error(412)
            self.objects[kw['Key']]=kw['Body']
        return {}
    def get_object(self,**kw):
        self.check('get',kw)
        if kw['Key'] not in self.objects: raise S3Error(404)
        data=self.objects[kw['Key']]
        return {'Body':io.BytesIO(data),'ContentLength':len(data)}
    def head_object(self,**kw):
        self.check('head',kw)
        if kw['Key'] not in self.objects: raise S3Error(404)
        return {'ContentLength':len(self.objects[kw['Key']])}
    def delete_object(self,**kw):
        self.check('delete',kw); self.objects.pop(kw['Key'],None); return {}


def remote(tmp_path, client=None):
    settings=SimpleNamespace(storage_root=tmp_path, r2_bucket_name='r2-worker-test',r2_key_prefix='worker-test/')
    c=client or FakeS3()
    return R2Storage(settings,client=c),c


@pytest.mark.asyncio
async def test_result_envelope_remote_restart_immutable_and_transient(tmp_path):
    from backend.storage.result_store import R2ResultStore
    s,c=remote(tmp_path/'one'); results=R2ResultStore(s); key=str(uuid4())
    payload={'caption':'원본 한 문장','asset_id':None}
    checksum=await results.save(key,payload)
    assert checksum==hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    await results.save(key,payload)
    with pytest.raises(ValueError): await results.save(key,{'caption':'changed'})
    shutil.rmtree(s.root)
    s2,_=remote(tmp_path/'two',c); results=R2ResultStore(s2)
    assert await results.load(key,checksum)==payload
    assert await results.load(key,'wrong') is None
    assert await results.load(str(uuid4())) is None
    c.error=503
    with pytest.raises(StorageUnavailable): await results.load(key)


@pytest.mark.asyncio
@pytest.mark.parametrize('data',[b'not-json',b'[]',b'{}',b'{"payload":123}',b'x'*(1024*1024+1)],ids=['invalid-json','list','missing','wrong-type','oversize'])
async def test_corrupt_envelope_is_absent(tmp_path,data):
    from backend.storage.result_store import R2ResultStore
    s,c=remote(tmp_path); key=str(uuid4())
    c.objects['worker-test/attempts/'+key+'.json']=data
    assert await R2ResultStore(s).load(key) is None


def test_stat_uses_remote_head_without_materializing(tmp_path):
    s,c=remote(tmp_path); key='/'.join([str(uuid4()) for _ in range(3)])+'/source'
    c.objects['worker-test/'+key]=b'raw'
    assert s.stat(key).st_size==3
    assert c.calls==[('head','worker-test/'+key)]
    assert not (s.root/key).exists()
    for size in (-1,True,20*1024*1024+1,None):
        c.head_object=lambda **kw: {'ContentLength':size}
        with pytest.raises(ValueError): s.stat(key)


async def r2_pipeline(client,db,tmp_path,monkeypatch):
    from backend.storage.result_store import R2ResultStore
    from backend.generation.fake_adapter import FakeExecutor
    me,album,run_id,local,_,_=await pipeline(client,db,tmp_path)
    store,c=remote(tmp_path/'r2-cache')
    async with db() as session:
        assets=list(await session.scalars(select(MediaAsset)))
    for asset in assets:
        c.objects['worker-test/'+asset.storage_key]=local.path(asset.storage_key).read_bytes()
    shutil.rmtree(local.root)
    executor=FakeExecutor(db,store)
    runner=Runner(db,R2ResultStore(store),executor,local_executor=executor,lease_seconds=10,heartbeat_seconds=.05)
    return me,album,run_id,store,c,executor,runner


@pytest.mark.asyncio
async def test_remote_generation_from_empty_cache_and_original_checksums(client,db,tmp_path,monkeypatch):
    me,album,run_id,store,c,executor,runner=await r2_pipeline(client,db,tmp_path,monkeypatch)
    source={k:v for k,v in c.objects.items()}
    await drain(runner)
    async with db() as s:
        assert (await s.get(Run,run_id)).status=='succeeded'
        assets=list(await s.scalars(select(MediaAsset)))
        for asset in assets:
            assert hashlib.sha256(c.objects['worker-test/'+asset.storage_key]).hexdigest()==asset.sha256
        attempts=list(await s.scalars(select(Attempt)))
        assert all([await runner.store.load(str(a.id)) is not None for a in attempts])
    assert all(c.objects[k]==v for k,v in source.items())
    assert not list(store.root.glob('attempts/*'))


@pytest.mark.asyncio
@pytest.mark.parametrize('stage',['caption','image_transform'])
async def test_remote_original_recovery_new_cache_no_second_execution(client,db,tmp_path,monkeypatch,stage):
    from backend.generation.fake_adapter import FakeExecutor
    from backend.storage.result_store import R2ResultStore
    me,album,run_id,store,c,executor,runner=await r2_pipeline(client,db,tmp_path,monkeypatch)
    claim,attempt_id,result=await preserved_original(db,runner,executor,run_id,stage)
    async with db() as s,s.begin():
        task=await s.get(Task,claim.task_id); task.lease_until=utcnow()-timedelta(seconds=1)
    shutil.rmtree(store.root)
    fresh,_=remote(tmp_path/'fresh-cache',c)
    class NeverExecute(FakeExecutor):
        async def execute(self,*args): raise AssertionError('original must never execute twice')
    adapter=NeverExecute(db,fresh)
    restarted=Runner(db,R2ResultStore(fresh),adapter,local_executor=adapter)
    assert await restarted.recover()==1
    async with db() as s:
        task=await s.get(Task,claim.task_id)
        assert task.status=='succeeded' and task.attempt_count==1
        assert await s.scalar(select(func.count()).select_from(Attempt).where(Attempt.task_id==claim.task_id))==1
    assert await restarted.store.load(str(attempt_id))==result


async def r2_pending(client,db,tmp_path,monkeypatch):
    import backend.uploads.validation as validation
    me,album,u,path,data=await pending(client)
    store,c=remote(tmp_path/'validation-cache')
    async with db() as s,s.begin():
        upload=await s.get(Upload,UUID(u['upload_id']))
        asset=await s.get(MediaAsset,upload.asset_id)
        upload.validation_config={**upload.validation_config,'storage_mode':'r2'}
        key=asset.storage_key
    c.objects['worker-test/'+key]=data
    monkeypatch.setattr(validation,'media_storage',lambda settings:store)
    worker=validation.ValidationWorker(db,config(storage_root=store.root,dev_ai_enabled=True))
    return worker,c,me,album,u,path,data,key


@pytest.mark.asyncio
async def test_remote_validation_keeps_source_and_normalizes(client,db,tmp_path,monkeypatch):
    worker,c,me,album,u,path,data,key=await r2_pending(client,db,tmp_path,monkeypatch)
    assert worker.store.mode=='r2' and await worker.run_once()
    assert c.objects['worker-test/'+key]==data
    async with db() as s:
        upload=await s.get(Upload,UUID(u['upload_id'])); page=await s.get(Page,upload.page_id)
        assert upload.status=='ready' and page.normalized_asset_id
        asset=await s.get(MediaAsset,page.normalized_asset_id)
        assert hashlib.sha256(c.objects['worker-test/'+asset.storage_key]).hexdigest()==asset.sha256


@pytest.mark.asyncio
async def test_remote_transient_validation_retries_not_rejects(client,db,tmp_path,monkeypatch):
    worker,c,me,album,u,path,data,key=await r2_pending(client,db,tmp_path,monkeypatch)
    c.error=503
    with pytest.raises(StorageUnavailable): await worker.run_once()
    async with db() as s:
        assert (await s.get(Upload,UUID(u['upload_id']))).status=='validating'
        job=await s.scalar(select(Job).where(Job.kind=='validate_upload'))
        assert job.status=='retry_wait'


@pytest.mark.asyncio
async def test_sdk_sleep_does_not_block_validation_loop(client,db,tmp_path,monkeypatch):
    worker,c,*_=await r2_pending(client,db,tmp_path,monkeypatch)
    c.delay=.06
    gaps=[]; running=True
    async def tick():
        last=time.monotonic()
        while running:
            await asyncio.sleep(.005)
            stamp=time.monotonic(); gaps.append(stamp-last); last=stamp
    ticker=asyncio.create_task(tick())
    try: assert await worker.run_once()
    finally:
        running=False; await ticker
    assert len(gaps)>20 and max(gaps)<.05


@pytest.mark.asyncio
@pytest.mark.parametrize('damage',['missing','checksum','oversize','mode'])
async def test_validation_bad_remote_inputs_never_link(client,db,tmp_path,monkeypatch,damage):
    worker,c,me,album,u,path,data,key=await r2_pending(client,db,tmp_path,monkeypatch)
    if damage=='missing': c.objects.pop('worker-test/'+key)
    elif damage=='checksum': c.objects['worker-test/'+key]=b'x'*len(data)
    elif damage=='oversize': c.objects['worker-test/'+key]=b'x'*(20*1024*1024+1)
    else:
        async with db() as s,s.begin():
            upload=await s.get(Upload,UUID(u['upload_id']))
            upload.validation_config={**upload.validation_config,'storage_mode':'local'}
    assert await worker.run_once()
    async with db() as s:
        upload=await s.get(Upload,UUID(u['upload_id'])); page=await s.get(Page,upload.page_id)
        assert upload.status=='rejected' and page.normalized_asset_id is None
    assert not any(k.endswith('/normalized') for k in c.objects)


@pytest.mark.asyncio
async def test_validation_scope_mismatch_cancels_without_remote_io(client,db,tmp_path,monkeypatch):
    from backend.models import User
    worker,c,me,album,u,path,data,key=await r2_pending(client,db,tmp_path,monkeypatch)
    async with db() as s,s.begin():
        other=User();s.add(other);await s.flush()
        asset=await s.get(MediaAsset,UUID(u['asset_id']));asset.owner_id=other.id
    assert await worker.run_once()
    async with db() as s:
        assert (await s.scalar(select(Job).where(Job.kind=='validate_upload'))).status=='cancelled'
    assert not c.calls


@pytest.mark.asyncio
async def test_deleted_during_normalize_cleans_late_objects_then_sweep(client,db,tmp_path,monkeypatch):
    import backend.uploads.validation as validation
    from backend.worker.jobs import enqueue_job
    worker,c,me,album,u,path,data,key=await r2_pending(client,db,tmp_path,monkeypatch)
    original=validation.normalize_in_process
    async def removed(*args,**kwargs):
        result=await original(*args,**kwargs)
        async with db() as s,s.begin():
            a=await s.get(Album,UUID(album));a.status='deleted';a.deleted_at=utcnow()
        return result
    monkeypatch.setattr(validation,'normalize_in_process',removed)
    assert await worker.run_once()
    assert 'worker-test/'+key.rsplit('/',1)[0]+'/normalized' not in c.objects
    # Cleanup all original objects; a late PUT then arrives under another role.
    async with db() as s,s.begin(): await enqueue_job(s,'cleanup_asset',UUID(u['asset_id']))
    assert await worker.run_once()
    assert not c.objects
    late=key.rsplit('/',1)[0]+'/result_thumbnail'
    c.objects['worker-test/'+late]=b'late'
    assert await worker._scan_deleted_assets(100)==1
    assert await worker.run_once()
    assert not c.objects
    # The first canonical source is still missing; repeated sweep revisits tombstones.
    c.objects['worker-test/'+late]=b'late-again'
    assert await worker._scan_deleted_assets(100)==1
    assert await worker.run_once() and not c.objects


@pytest.mark.asyncio
@pytest.mark.parametrize('damage',['none','corrupt','transient'])
async def test_image_original_blob_without_envelope_recovery(client,db,tmp_path,monkeypatch,damage):
    from backend.storage.result_store import R2ResultStore
    from backend.generation.fake_adapter import FakeExecutor
    me,album,run_id,store,c,executor,runner=await r2_pipeline(client,db,tmp_path,monkeypatch)
    claim,attempt_id,result=await preserved_original(db,runner,executor,run_id,'image_transform')
    store.delete_envelope(str(attempt_id))
    async with db() as s,s.begin():
        task=await s.get(Task,claim.task_id);task.lease_until=utcnow()-timedelta(seconds=1)
        attempt=await s.get(Attempt,attempt_id)
        asset=await s.get(MediaAsset,attempt.output_asset_id);output_key=asset.storage_key
    if damage=='corrupt':
        # A different valid 3:4 WebP is not the preserved original.
        from PIL import Image
        out=io.BytesIO();Image.new('RGB',(30,40),'blue').save(out,format='WEBP',lossless=True)
        c.objects['worker-test/'+output_key]=out.getvalue()
    shutil.rmtree(store.root)
    fresh,_=remote(tmp_path/'original-cache',c)
    restarted=Runner(db,R2ResultStore(fresh),FakeExecutor(db,fresh))
    if damage=='transient':
        c.error=503
        with pytest.raises(StorageUnavailable): await restarted.recover()
    else:
        assert await restarted.recover()==(1 if damage=='none' else 0)
    async with db() as s:
        task=await s.get(Task,claim.task_id)
        assert task.status==('succeeded' if damage=='none' else 'unknown' if damage=='corrupt' else 'running')
        assert task.attempt_count==1


@pytest.mark.asyncio
async def test_sdk_downloads_do_not_block_generation_loop(client,db,tmp_path,monkeypatch):
    me,album,run_id,store,c,executor,runner=await r2_pipeline(client,db,tmp_path,monkeypatch)
    c.delay=.06
    main_thread=threading.get_ident(); threads=[]; check=c.check
    def threaded(*args):
        threads.append(threading.get_ident());return check(*args)
    c.check=threaded
    ticks=0; running=True
    async def tick():
        nonlocal ticks
        while running:
            await asyncio.sleep(.005);ticks+=1
    ticker=asyncio.create_task(tick())
    try: await drain(runner)
    finally:
        running=False;await ticker
    assert ticks>100 and threads and main_thread not in threads
    async with db() as s: assert (await s.get(Run,run_id)).status=='succeeded'


async def prioritize_stage(db,run_id,stage):
    async with db() as s,s.begin():
        tasks=list(await s.scalars(select(Task).where(Task.run_id==run_id)))
        chosen=next(t for t in tasks if t.stage==stage and t.status=='queued')
        for task in tasks:
            if task.status=='queued' and task.id!=chosen.id:
                task.next_retry_at=utcnow()+timedelta(hours=1)
        return chosen.id


@pytest.mark.asyncio
@pytest.mark.parametrize('stage,operation,fail_at',[
    ('caption','get',1),('image_transform','get',1),
    # One authoritative snapshot per stage: duplicate GET/HEAD no longer exist.
])
async def test_pre_result_r2_failure_can_resume(client,db,tmp_path,monkeypatch,stage,operation,fail_at):
    from backend.tests.integration.test_generation_http import resume
    me,album,run_id,store,c,executor,runner=await r2_pipeline(client,db,tmp_path,monkeypatch)
    task_id=await prioritize_stage(db,run_id,stage)
    check=c.check;seen=0
    def unavailable(op,kw):
        nonlocal seen
        if op==operation:
            seen+=1
            if seen==fail_at:raise S3Error(503)
        return check(op,kw)
    monkeypatch.setattr(c,'check',unavailable)
    assert await runner.run_once()
    async with db() as s:
        task=await s.get(Task,task_id)
        attempt=await s.scalar(select(Attempt).where(Attempt.task_id==task_id))
        assert task.status=='failed'
        assert task.safe_to_retry and task.error_code=='MEDIA_SAVE_FAILED'
        assert attempt.dispatch_state=='not_sent'
        assert attempt.output_asset_id is None and attempt.output_caption is None
        assert await runner.store.load(str(attempt.id)) is None
        album_row=await s.get(Album,UUID(album));version=album_row.version
        assert album_row.status=='action_required'
    monkeypatch.setattr(c,'check',check)
    assert (await resume(client,me,album,str(run_id),version)).status_code==202
    async with db() as s,s.begin():
        for task in await s.scalars(select(Task).where(Task.run_id==run_id)):
            task.next_retry_at=None
    await drain(runner)
    async with db() as s:
        assert (await s.get(Run,run_id)).status=='succeeded'
        assert (await s.get(Album,UUID(album))).status=='review_ready'
        assert (await s.get(Task,task_id)).attempt_count==2


@pytest.mark.asyncio
@pytest.mark.parametrize('stage,boundary',[
    ('caption','envelope'),('image_transform','envelope'),('image_transform','blob'),
])
async def test_post_result_r2_failure_preserves_original(client,db,tmp_path,monkeypatch,stage,boundary):
    from backend.generation.fake_adapter import FakeExecutor
    me,album,run_id,store,c,executor,runner=await r2_pipeline(client,db,tmp_path,monkeypatch)
    task_id=await prioritize_stage(db,run_id,stage)
    put=c.put_object
    def response_lost(**kw):
        result=put(**kw)
        if (boundary=='envelope' and '/attempts/' in kw['Key']
            or boundary=='blob' and kw['Key'].endswith('/transform_output')):
            raise S3Error(503)
        return result
    monkeypatch.setattr(c,'put_object',response_lost)
    assert await runner.run_once()
    async with db() as s:
        task=await s.get(Task,task_id)
        attempt=await s.scalar(select(Attempt).where(Attempt.task_id==task_id))
        assert task.status=='unknown' and not task.safe_to_retry
        assert attempt.dispatch_state=='accepted_or_unknown'
    monkeypatch.setattr(c,'put_object',put)
    async def never_execute(*args):raise AssertionError('preserved result must not execute again')
    monkeypatch.setattr(FakeExecutor,'execute',never_execute)
    assert await runner.recover()==1
    async with db() as s:
        task=await s.get(Task,task_id)
        assert task.status=='succeeded' and task.attempt_count==1
        assert await s.scalar(select(func.count()).select_from(Attempt).where(Attempt.task_id==task_id))==1


@pytest.mark.asyncio
async def test_validation_downloads_source_once(client,db,tmp_path,monkeypatch):
    worker,c,me,album,u,path,data,key=await r2_pending(client,db,tmp_path,monkeypatch)
    c.calls.clear()
    assert await worker.run_once()
    assert [op for op,k in c.calls if k=='worker-test/'+key]==['get']
    async with db() as s:
        assert (await s.get(Upload,UUID(u['upload_id']))).status=='ready'


@pytest.mark.asyncio
@pytest.mark.parametrize('stage',['caption','image_transform'])
async def test_generation_fetches_each_input_once(client,db,tmp_path,monkeypatch,stage):
    me,album,rid,store,c,executor,runner=await r2_pipeline(client,db,tmp_path,monkeypatch)
    tid=await prioritize_stage(db,rid,stage)
    c.calls.clear()
    assert await runner.run_once()
    reads=[key for op,key in c.calls if op=='get' and key.endswith('/normalized')]
    assert len(reads)==1
    assert not [op for op,key in c.calls if op=='head' and key.endswith('/normalized')]
    async with db() as s:assert (await s.get(Task,tid)).status=='succeeded'
