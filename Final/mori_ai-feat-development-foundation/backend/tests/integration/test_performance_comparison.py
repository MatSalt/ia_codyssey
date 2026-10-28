"""Repeatable DB/codec benchmark with controlled provider latency; no paid API."""
import asyncio
import json
from time import perf_counter
from sqlalchemy import select
import pytest
from backend.models import Run
from backend.tests.integration.test_real_generation_pipeline import client, real_pipeline
from backend.worker.scheduler import run_worker


@pytest.mark.asyncio
async def test_same_inputs_serial_vs_parallel_provider_latency(client,db,tmp_path):
    results=[]
    for mode in ('serial','parallel'):
        _,_,rid,_,executor,runner,provider,_=await real_pipeline(client,db,tmp_path/mode,count=6)
        respond=provider.respond
        active=0;peak=0
        async def delayed(stage,image):
            nonlocal active,peak
            active+=1;peak=max(peak,active)
            try:
                await asyncio.sleep(3 if stage=='image_transform' else 1.5)
                return await respond(stage,image)
            finally:active-=1
        provider.respond=delayed
        started=perf_counter()
        if mode=='serial':
            for _ in range(30):
                if not await runner.run_once():break
        else:
            class Validation:
                async def run_once(self):return False
                async def scan_incomplete_uploads(self,*args,**kwargs):pass
            stopped=asyncio.Event()
            worker=asyncio.create_task(run_worker(Validation(),runner,stopped,poll_seconds=.01))
            try:
                async with asyncio.timeout(90):
                    while True:
                        async with db() as s:
                            if (await s.get(Run,rid)).status=='succeeded':break
                        await asyncio.sleep(.05)
            finally:
                stopped.set();await worker
        elapsed=perf_counter()-started
        async with db() as s:assert (await s.get(Run,rid)).status=='succeeded'
        results.append({'mode':mode,'elapsed_seconds':round(elapsed,3),'provider_peak':peak,'provider_calls':len(provider.calls)})
    assert results[0]['provider_calls']==results[1]['provider_calls']==9
    assert results[0]['provider_peak']==1 and results[1]['provider_peak']>1
    print('PERFORMANCE_COMPARISON '+json.dumps(results),flush=True)
