from uuid import UUID, uuid4
from io import BytesIO
import httpx
import pytest
from PIL import Image
from backend.main import create_app
from backend.storage.local import LocalStorage
from backend.tests.integration.test_auth_http import config, login, ORIGIN
from backend.tests.integration.test_album_http import headers
from backend.tests.integration.test_upload_http import consent

@pytest.mark.asyncio
async def test_goods_lifecycle_isolation_replay_and_abandon(db, tmp_path):
    settings=config(dev_ai_enabled=True)
    store=LocalStorage(tmp_path)
    app=create_app(settings=settings,session_factory=db,media_storage=store)
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url=ORIGIN) as c:
        me=await login(c);await consent(c,me)
        r=await c.post('/api/v1/goods/work',json={},headers=headers(me,'work'))
        assert r.status_code==201
        work=r.json()['data']['id']
        assert (await c.post('/api/v1/goods/work',json={},headers=headers(me,'work'))).json()['data']['id']==work
        assert (await c.post(f'/api/v1/goods/work/{work}/revisions',json={'style':'photo','message':'작은 액자','parent_id':None},headers=headers(me,'gen'))).status_code==422
        out=BytesIO();Image.new('RGB',(40,40),'blue').save(out,format='PNG')
        assert (await c.put(f'/api/v1/goods/work/{work}/source',content=out.getvalue(),headers={**headers(me,'upload'),'Content-Type':'image/png'})).status_code==200
        body={'style':'photo','message':'작은 액자','parent_id':None}
        gen=await c.post(f'/api/v1/goods/work/{work}/revisions',json=body,headers=headers(me,'gen'))
        assert gen.status_code==202
        rid=gen.json()['data']['id']
        assert (await c.post(f'/api/v1/goods/work/{work}/revisions',json=body,headers=headers(me,'gen'))).json()['data']['id']==rid
        from backend.goods_design.worker import GoodsWorker
        worker=GoodsWorker(db,store,settings)
        assert await worker.run_once()
        state=(await c.get(f'/api/v1/goods/work/{work}')).json()['data']
        assert state['revisions'][0]['status']=='ready'
        assert (await c.get(state['revisions'][0]['image_url'])).status_code==200
        finish={'revision_id':rid,'placement':{'holeX':.5,'holeY':0,'widthMm':50}}
        completed=await c.post(f'/api/v1/goods/work/{work}/complete',json=finish,headers=headers(me,'finish'))
        assert completed.status_code==200
        design=completed.json()['data']['id']
        assert (await c.get('/api/v1/goods/designs')).json()['data']['items'][0]['id']==design
        assert (await c.post(f'/api/v1/goods/work/{work}/complete',json=finish,headers=headers(me,'finish'))).json()['data']['id']==design
        # Leaving a completed work must not erase the saved design.
        await c.delete(f'/api/v1/goods/work/{work}',headers=headers(me,'discard'))
        assert (await c.get(f'/api/v1/goods/designs/{design}')).status_code==200
        other=await login(c,'beta');await consent(c,other)
        assert (await c.get(f'/api/v1/goods/designs/{design}')).status_code==404
        assert (await c.get(state['revisions'][0]['image_url'])).status_code==404
        assert (await c.get('/api/v1/goods/designs')).json()['data']['items']==[]

@pytest.mark.asyncio
async def test_discard_blocks_late_work_and_album_lock(db,tmp_path):
    from backend.models import User,Album
    from backend.goods_design.models import GoodsWork,GoodsRevision,GoodsDesign
    from backend.goods_design.service import link_album, discard
    from backend.http.errors import APIError
    from datetime import datetime,timezone,timedelta
    async with db() as s,s.begin():
        u=User();s.add(u);await s.flush()
        w=GoodsWork(owner_id=u.id,expires_at=datetime.now(timezone.utc)+timedelta(hours=1));s.add(w);await s.flush()
        r=GoodsRevision(work_id=w.id,request_key='a',request_hash='a',style='photo',message='x',prompt='x',config={},status='ready');s.add(r);await s.flush()
        d=GoodsDesign(owner_id=u.id,work_id=w.id,revision_id=r.id,placement={},production_started_at=datetime.now(timezone.utc));s.add(d)
        a=Album(owner_id=u.id,status='published',published_at=datetime.now(timezone.utc));s.add(a);await s.flush()
        with pytest.raises(APIError) as err:await link_album(s,u.id,d.id,a.id,1)
        assert err.value.status==409
        # No design for the second temporary work: discard invalidates its execution.
        w2=GoodsWork(owner_id=u.id,expires_at=datetime.now(timezone.utc)+timedelta(hours=1));s.add(w2);await s.flush()
        await discard(s,u.id,w2.id)
        assert w2.status=='discarded'

@pytest.mark.asyncio
async def test_goods_discard_late_result_and_unknown_never_retries(db,tmp_path):
    import asyncio
    from datetime import datetime,timezone,timedelta
    from sqlalchemy import select
    from backend.models import User,AIBudgetEntry
    from backend.goods_design.models import GoodsWork,GoodsRevision
    from backend.goods_design.worker import GoodsWorker
    from backend.goods_design.service import discard
    from backend.generation.openai_provider import ProviderResult,ProviderFailure
    from decimal import Decimal
    store=LocalStorage(tmp_path)
    async def seed():
        async with db() as s,s.begin():
            u=User();s.add(u);await s.flush()
            w=GoodsWork(owner_id=u.id,expires_at=datetime.now(timezone.utc)+timedelta(hours=1));s.add(w);await s.flush()
            w.source_key=f'{u.id}/{w.id}/{w.id}/source'
            r=GoodsRevision(work_id=w.id,request_key='x',request_hash='a',style='photo',message='x',prompt='x',config={'mode':'real','model':'gpt-image-2'});s.add(r);await s.flush()
            store.write(w.source_key,b'input');return u.id,w.id,r.id
    owner,wid,rid=await seed()
    started=asyncio.Event();release=asyncio.Event()
    class Provider:
        calls=0
        async def generate(self,*args):
            self.calls+=1;started.set();await release.wait();return ProviderResult(image=b'output',cost_usd=Decimal('.1'))
    provider=Provider();worker=GoodsWorker(db,store,config(ai_real_calls_enabled=True,openai_api_key='test'),provider)
    task=asyncio.create_task(worker.run_once());await started.wait()
    async with db() as s,s.begin():await discard(s,owner,wid)
    release.set();await task;await worker.maintenance()
    async with db() as s:
        r=await s.get(GoodsRevision,rid);assert r.status=='cancelled'
        assert not store.exists(f'{owner}/{wid}/{rid}/result')
        entry=await s.get(AIBudgetEntry,rid);assert entry.actual_usd==Decimal('.1')
    owner,wid,rid=await seed()
    class Unknown:
        calls=0
        async def generate(self,*args):self.calls+=1;raise ProviderFailure('AI_RESULT_UNKNOWN')
    provider=Unknown();worker=GoodsWorker(db,store,config(ai_real_calls_enabled=True,openai_api_key='test'),provider)
    assert await worker.run_once();assert not await worker.run_once();assert provider.calls==1
    async with db() as s:
        assert (await s.get(GoodsRevision,rid)).status=='unknown'
        assert (await s.get(AIBudgetEntry,rid)).status=='unknown'

@pytest.mark.asyncio
async def test_goods_album_ownership_version_and_source_preservation(db,tmp_path):
    from datetime import datetime,timezone
    from backend.models import Album,User
    app=create_app(settings=config(dev_ai_enabled=True),session_factory=db,media_storage=LocalStorage(tmp_path))
    async with app.router.lifespan_context(app),httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url=ORIGIN) as c:
        me=await login(c);await consent(c,me)
        work=(await c.post('/api/v1/goods/work',json={},headers=headers(me))).json()['data']['id']
        out=BytesIO();Image.new('RGB',(40,40),'red').save(out,format='PNG')
        assert (await c.put(f'/api/v1/goods/work/{work}/source',content=out.getvalue(),headers=headers(me))).status_code==200
        assert (await c.put(f'/api/v1/goods/work/{work}/source',content=b'broken',headers=headers(me))).status_code==422
        gen=await c.post(f'/api/v1/goods/work/{work}/revisions',json={'style':'book','message':'책','parent_id':None},headers=headers(me,'g'))
        from backend.goods_design.worker import GoodsWorker
        await GoodsWorker(db,app.state.media_storage,app.state.settings).run_once()
        rid=gen.json()['data']['id']
        d=(await c.post(f'/api/v1/goods/work/{work}/complete',json={'revision_id':rid,'placement':{'holeX':.5,'holeY':0,'widthMm':50}},headers=headers(me))).json()['data']
        async with db() as s,s.begin():
            own=Album(owner_id=UUID(me['user']['id']),status='published',published_at=datetime.now(timezone.utc));s.add(own)
            other=User();s.add(other);await s.flush();foreign=Album(owner_id=other.id,status='published');s.add(foreign);await s.flush()
            own_id,foreign_id=str(own.id),str(foreign.id)
        url=f'/api/v1/goods/designs/{d["id"]}/album'
        assert (await c.put(url,json={'album_id':foreign_id,'expected_version':1},headers=headers(me))).status_code==404
        assert (await c.put(url,json={'album_id':own_id,'expected_version':1},headers=headers(me))).status_code==200
        assert (await c.put(url,json={'album_id':own_id,'expected_version':1},headers=headers(me))).status_code==409
        assert (await c.post('/api/v1/goods/work',json={})).status_code==403

@pytest.mark.asyncio
async def test_goods_and_album_share_global_image_slots(db,seeded,tmp_path):
    from datetime import datetime,timezone,timedelta
    from backend.models import Task,Page,Album
    from backend.goods_design.models import GoodsWork,GoodsRevision
    from backend.goods_design.worker import GoodsWorker
    from backend.generation.repository import claim_task
    now=datetime.now(timezone.utc)
    async with db() as s,s.begin():
        album=await s.get(Album,seeded['album'])
        task=await s.get(Task,seeded['task']);task.stage='image_transform';task.status='running';task.lease_until=now+timedelta(minutes=5)
        page=Page(album_id=album.id,position=2,selection_index=2);s.add(page);await s.flush()
        s.add(Task(run_id=seeded['run'],page_id=page.id,stage='image_transform',status='running',lease_until=now+timedelta(minutes=5)))
        w=GoodsWork(owner_id=album.owner_id,source_key='unused',expires_at=now+timedelta(hours=1));s.add(w);await s.flush()
        r=GoodsRevision(work_id=w.id,request_key='g',request_hash='g',style='book',message='x',prompt='x',config={'mode':'fake','model':'fake'});s.add(r);await s.flush();rid=r.id
    assert not await GoodsWorker(db,LocalStorage(tmp_path),config(dev_ai_enabled=True)).run_once()
    async with db() as s,s.begin():
        assert (await s.get(GoodsRevision,rid)).status=='queued'
        tasks=(await s.scalars(__import__('sqlalchemy').select(Task))).all()
        for t in tasks:t.status='queued';t.lease_until=None
        r=await s.get(GoodsRevision,rid);r.status='running';r.lease_until=now+timedelta(minutes=5)
    async with db() as s:assert await claim_task(s,now,90,stage='image_transform') is not None
    async with db() as s:assert await claim_task(s,now,90,stage='image_transform') is None
