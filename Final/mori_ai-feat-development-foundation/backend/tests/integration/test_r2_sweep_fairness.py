"""PostgreSQL sweep fairness with an in-memory S3 boundary; no external R2."""
import asyncio
from collections import Counter
from uuid import UUID

import pytest
from sqlalchemy import select
from backend.models import Album, MediaAsset, Page
from backend.storage.local import storage_key
from backend.storage.r2 import StorageUnavailable
from backend.tests.integration.test_generation_pipeline import client
from backend.tests.integration.test_r2_pipeline import r2_pending
from backend.uploads.validation import now


@pytest.mark.asyncio
async def test_deleted_page_checks_each_key_once_and_rechecks_next_sweep(client,db,tmp_path,monkeypatch):
    worker,c,me,album,u,path,data,source=await r2_pending(client,db,tmp_path,monkeypatch)
    assert await worker.run_once()
    async with db() as s,s.begin():
        row=await s.get(Album,UUID(album));row.status='deleted';row.deleted_at=now()
        page=await s.scalar(select(Page).where(Page.album_id==row.id))
        late=storage_key(row.owner_id,row.id,page.id,'result_thumbnail')
        assert len(list(await s.scalars(select(MediaAsset).where(MediaAsset.page_id==page.id))))==3
    c.objects.clear();c.calls.clear()
    assert await worker._scan_deleted_assets(10)==0
    counts=Counter(key for op,key in c.calls if op=='head')
    assert len(counts)==6 and max(counts.values())==1
    # A source 404 cannot hide a late result, and absence is not cached across scans.
    c.objects['worker-test/'+late]=b'late'
    c.calls.clear()
    assert await worker._scan_deleted_assets(10)>0
    counts=Counter(key for op,key in c.calls if op=='head')
    assert max(counts.values())==1
    while await worker.run_once():pass
    assert not c.objects
    c.objects['worker-test/'+late]=b'later'
    assert await worker._scan_deleted_assets(10)>0
    while await worker.run_once():pass
    assert not c.objects


@pytest.mark.asyncio
@pytest.mark.parametrize('mode,error', [('r2',StorageUnavailable),('r2',TimeoutError),('r2','slow'),('local',None)])
async def test_main_keeps_jobs_running_with_independent_bounded_sweep(db,monkeypatch,mode,error):
    import backend.worker.__main__ as worker_main
    from backend.tests.integration.test_auth_http import config
    events=[];scans=[];stopped=asyncio.Event()
    class Validation:
        store=type('Store',(),{'mode':mode,'root':None})()
        def __init__(self,*args):pass
        async def run_once(self):
            events.append('job')
            if events.count('job')==4:stopped.set()
        async def scan_incomplete_uploads(self,stamp,limit=100):
            events.append('scan');scans.append(limit)
            if error=='slow':
                try:
                    await asyncio.Future()
                finally:
                    events.append('scan_cancelled')
            if error:raise error('injected sweep failure')
    class Runner:
        def __init__(self,*args,**kwargs):pass
        async def maintenance(self):events.append('maintenance')
    loop=asyncio.get_running_loop()
    monkeypatch.setattr(loop,'add_signal_handler',lambda *args:None)
    monkeypatch.setattr(loop,'remove_signal_handler',lambda *args:None)
    monkeypatch.setattr(worker_main.asyncio,'Event',lambda:stopped)
    monkeypatch.setattr(worker_main,'Settings',lambda:config(worker_poll_seconds=.01,dev_ai_enabled=False))
    monkeypatch.setattr(worker_main,'session_factory',lambda _:db)
    monkeypatch.setattr(worker_main,'ValidationWorker',Validation)
    monkeypatch.setattr(worker_main,'Runner',Runner)
    # This scheduler-isolation test replaces asyncio.Event globally. Stub the
    # newly added goods DB lane too: real asyncpg Events must not alias stopped.
    import backend.goods_design.worker as goods_module
    class Goods:
        provider=None
        def __init__(self,*args):pass
        async def maintenance(self):pass
    monkeypatch.setattr(goods_module,'GoodsWorker',Goods)
    import backend.storage.factory as factory
    monkeypatch.setattr(factory,'result_store',lambda _:None)
    await asyncio.wait_for(worker_main.main(),timeout=3)
    assert events[0]=='job'
    assert events.count('job')==4
    assert scans==[10]  # Both adapters now have an independent 30-second scan lane.
    if error=='slow':assert events[-1]=='scan_cancelled'
