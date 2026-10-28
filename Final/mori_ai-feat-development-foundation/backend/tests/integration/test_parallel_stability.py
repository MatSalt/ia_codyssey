"""Isolated DB stability probes; no external providers or user media."""
import asyncio
from collections import Counter
import json
import sys
from uuid import UUID
import pytest
from sqlalchemy import select, func
from backend.models import Run, Task, Attempt, Upload
from backend.tests.integration.test_real_generation_pipeline import client, real_pipeline
from backend.tests.integration.test_worker_concurrency import add_tasks


@pytest.mark.asyncio
@pytest.mark.parametrize('stage,cap', [('caption',4),('image_transform',2)])
async def test_processes_share_stage_slots(db,seeded,stage,cap):
    await add_tasks(db,seeded,stage,24)
    script='''
import asyncio,json,sys
from backend.database import session_factory
from backend.generation.repository import claim_task
from backend.worker.runner import utcnow
async def main():
 f=session_factory(); ids=[]
 for _ in range(8):
  async with f() as s:
   c=await claim_task(s,utcnow(),90,stage=sys.argv[1])
   if c: ids.append(str(c.task_id))
 await f.kw['bind'].dispose()
 print(json.dumps(ids))
asyncio.run(main())
'''
    processes=[]
    try:
        for _ in range(3):
            processes.append(await asyncio.create_subprocess_exec(sys.executable,'-c',script,stage,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE))
        outputs=await asyncio.wait_for(asyncio.gather(*(p.communicate() for p in processes)),30)
        assert all(p.returncode==0 for p in processes), [err.decode() for _,err in outputs]
        ids=[item for out,_ in outputs for item in json.loads(out)]
        assert len(ids)==len(set(ids))==cap
        print('PROCESS_CAP '+json.dumps({'processes':3,'contenders':24,'stage':stage,'claimed':len(ids)}))
    finally:
        for p in processes:
            if p.returncode is None: p.kill()
        await asyncio.gather(*(p.wait() for p in processes))


@pytest.mark.asyncio
async def test_fifty_pages_two_schedulers_and_new_uploads(client,db,tmp_path):
    from backend.worker.scheduler import run_worker
    from backend.uploads.validation import ValidationWorker
    from backend.tests.integration.test_validation_worker import image_bytes
    from backend.tests.integration.test_upload_http import setup, consent, reserve, file, headers
    _,_,rid,_,_,runner,provider,ledger=await real_pipeline(client,db,tmp_path,count=50)
    uploads=[]
    me,album=await setup(client);await consent(client,me)
    samples=[('photo.png',image_bytes('PNG')),('photo.jpg',image_bytes('JPEG')),('photo.heic',image_bytes('HEIF'))]
    response=await reserve(client,me,album,[file(name,len(data)) for name,data in samples])
    assert response.status_code==201
    for u,(_,data) in zip(response.json()['data']['uploads'],samples):
        assert (await client.put(u['upload_url'],content=data,headers={**u['required_headers'],**headers(me)})).status_code==204
        path=f'/api/v1/albums/{album}/uploads/{u["upload_id"]}/complete'
        assert (await client.post(path,json={},headers=headers(me))).status_code==202
        uploads.append(UUID(u['upload_id']))
    active=Counter();peaks=Counter();respond=provider.respond
    async def delayed(stage,image):
        active[stage]+=1;peaks[stage]=max(peaks[stage],active[stage])
        try:
            await asyncio.sleep(.2)
            return await respond(stage,image)
        finally: active[stage]-=1
    provider.respond=delayed
    app=client._transport.app
    validation=ValidationWorker(db,app.state.settings)
    stopped=asyncio.Event()
    workers=[asyncio.create_task(run_worker(validation,runner,stopped,poll_seconds=.02)) for _ in range(2)]
    try:
        async with asyncio.timeout(180):
            while True:
                async with db() as s:
                    done=(await s.get(Run,rid)).status=='succeeded'
                    ready=await s.scalar(select(func.count()).select_from(Upload).where(Upload.id.in_(uploads),Upload.status=='ready'))
                    if done and ready==3: break
                await asyncio.sleep(.1)
    finally:
        stopped.set();await asyncio.gather(*workers)
    async with db() as s:
        tasks=list(await s.scalars(select(Task).where(Task.run_id==rid)))
        assert len(tasks)==150 and all(t.status=='succeeded' for t in tasks)
        attempts=list(await s.scalars(select(Attempt).join(Task).where(Task.run_id==rid)))
        assert max(Counter(a.task_id for a in attempts).values())==1
    counts=Counter(stage for stage,_ in provider.calls)
    assert counts=={'caption':50,'image_transform':25}
    assert 1<peaks['caption']<=4 and 1<peaks['image_transform']<=2
    assert sum(active.values())==0
    print('PARALLEL_STABILITY '+json.dumps({'pages':50,'schedulers':2,'new_uploads_ready':3,'tasks_succeeded':150,'provider_calls':counts,'provider_peaks':peaks}))
