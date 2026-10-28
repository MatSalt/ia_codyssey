"""R2 HTTP contracts using a remote stub and real PostgreSQL, never credentials."""
import hashlib
from types import SimpleNamespace
from uuid import UUID
import pytest
import pytest_asyncio
from backend.tests.integration.test_auth_http import client, login
from backend.tests.integration.test_upload_http import setup, consent, reserve, file, headers
from backend.models import Upload, MediaAsset, Page

class StubStorage:
    mode = 'r2'
    payload = b'abcd'
    failure = None
    calls = 0
    def stat(self, key):
        self.calls += 1
        if self.failure: raise self.failure
        return SimpleNamespace(st_size=len(self.payload))
    def checksum(self, key): return hashlib.sha256(self.payload).hexdigest()
    def read_bytes(self, key):
        self.calls += 1
        if self.failure: raise self.failure
        return self.payload

class FakeSigner:
    mode = 'r2'
    def __init__(self): self.reads = []
    def upload_url(self, key, path, entity, expires, mime, declared):
        return 'https://r2.invalid/'+key, {'Content-Type':mime,'If-None-Match':'*'}
    def read_url(self, key, path, entity, expires, mime):
        self.reads.append(key)
        return 'https://r2.invalid/'+key
    def url(self, *args): return 'https://legacy.invalid/'

@pytest_asyncio.fixture
async def remote(client):
    app=client._transport.app
    store=StubStorage(); signing=FakeSigner()
    app.state.media_storage=store; app.state.media_signer=signing
    return store, signing

async def reserved(client):
    me,a=await setup(client); await consent(client,me)
    result=await reserve(client,me,a,[file(size=4)])
    assert result.status_code==201
    u=result.json()['data']['uploads'][0]
    return me,a,u,f'/api/v1/albums/{a}/uploads/{u["upload_id"]}/complete'

@pytest.mark.asyncio
async def test_reservation_snapshot_and_headers(client,db,remote):
    me,a,u,path=await reserved(client)
    assert u['required_headers']=={'Content-Type':'image/png','If-None-Match':'*'}
    assert u['upload_url'].startswith('https://r2.invalid/')
    async with db() as s:
        row=await s.get(Upload,UUID(u['upload_id']))
        assert row.validation_config['storage_mode']=='r2'
        assert 899 <= (row.expires_at-row.created_at).total_seconds() <= 900

@pytest.mark.asyncio
async def test_complete_requires_hash_matches_bytes_and_replay(client,db,remote):
    me,a,u,path=await reserved(client)
    for body in ({},{'sha256':'BAD'},{'sha256':'a'*64,'extra':1}):
        assert (await client.post(path,json=body,headers=headers(me))).status_code==422
    wrong=await client.post(path,json={'sha256':'0'*64},headers=headers(me))
    assert wrong.status_code==409
    digest=hashlib.sha256(b'abcd').hexdigest()
    for _ in range(2):
        response=await client.post(path,json={'sha256':digest},headers=headers(me))
        assert response.status_code==202
        assert digest not in response.text
    assert (await client.post(path,json={'sha256':'0'*64},headers=headers(me))).status_code==409
    async with db() as s,s.begin(): (await s.get(Upload,UUID(u['upload_id']))).status='ready'
    assert (await client.post(path,json={'sha256':digest},headers=headers(me))).status_code==200
    assert (await client.post(path,json={'sha256':'0'*64},headers=headers(me))).status_code==409

@pytest.mark.asyncio
async def test_remote_not_ready_size_and_owner_before_io(client,db,remote):
    store,_=remote
    me,a,u,path=await reserved(client)
    body={'sha256':hashlib.sha256(b'abcd').hexdigest()}
    store.failure=FileNotFoundError()
    r=await client.post(path,json=body,headers=headers(me)); assert r.status_code==422 and r.json()['error']['code']=='UPLOAD_NOT_READY'
    store.failure=None; store.payload=b'abc'
    assert (await client.post(path,json=body,headers=headers(me))).status_code==422
    beta=await login(client,'beta'); calls=store.calls
    assert (await client.post(path,json={},headers=headers(beta))).status_code==404
    assert store.calls==calls

@pytest.mark.asyncio
async def test_local_private_routes_are_disabled(client,db,remote):
    me,a,u,path=await reserved(client)
    assert (await client.put(f'/api/v1/private/uploads/{u["upload_id"]}?expires=1&signature=x',content=b'abcd',headers=headers(me))).status_code==404
    assert (await client.get(f'/api/v1/private/albums/{a}/media/{u["asset_id"]}?expires=1&signature=x')).status_code==404

@pytest.mark.asyncio
async def test_transient_is_retryable_and_does_not_expose_hash(client,db,remote):
    from backend.storage.r2 import StorageUnavailable
    store,_=remote
    me,a,u,path=await reserved(client)
    store.failure=StorageUnavailable('internal remote details')
    digest=hashlib.sha256(b'abcd').hexdigest()
    response=await client.post(path,json={'sha256':digest},headers=headers(me))
    assert response.status_code==503
    assert response.json()['error']['code']=='TEMPORARILY_UNAVAILABLE'
    assert response.json()['error']['retryable'] is True
    assert digest not in response.text and 'internal remote' not in response.text
    async with db() as s: assert (await s.get(Upload,UUID(u['upload_id']))).status=='reserved'

@pytest.mark.asyncio
async def test_removed_and_expired_never_touch_remote(client,db,remote):
    from datetime import datetime,timezone,timedelta
    store,_=remote
    me,a,u,path=await reserved(client)
    async with db() as s,s.begin():
        (await s.get(Upload,UUID(u['upload_id']))).expires_at=datetime.now(timezone.utc)-timedelta(seconds=1)
    response=await client.post(path,json={},headers=headers(me))
    assert response.status_code==200 and response.json()['data']['status']=='expired'
    async with db() as s,s.begin():
        (await s.get(Page,UUID(u['page_id']))).removed_at=datetime.now(timezone.utc)
    assert (await client.post(path,json={},headers=headers(me))).status_code==404
    assert store.calls==0

@pytest.mark.asyncio
async def test_read_signer_gets_canonical_key_and_rejects_corrupt_current_asset(client,db,remote):
    from uuid import uuid4
    from backend.storage.local import storage_key
    me,a,u,path=await reserved(client); store,signing=remote
    asset_id=uuid4()
    async with db() as s,s.begin():
        source=await s.get(MediaAsset,UUID(u['asset_id']))
        asset=MediaAsset(id=asset_id,owner_id=source.owner_id,album_id=source.album_id,page_id=source.page_id,role='thumbnail',storage_key=storage_key(source.owner_id,source.album_id,source.page_id,'thumbnail'),mime='image/webp',status='ready',width=3,height=4)
        s.add(asset);await s.flush()
        (await s.get(Page,source.page_id)).thumbnail_asset_id=asset_id
        key=asset.storage_key
    response=await client.get('/api/v1/albums/'+a)
    assert response.status_code==200 and response.json()['data']['media_access'][0]['url']=='https://r2.invalid/'+key
    access=f'/api/v1/albums/{a}/media-access'
    assert (await client.post(access,json={'asset_ids':[str(asset_id)]},headers=headers(me))).status_code==200
    calls=len(signing.reads)
    async with db() as s,s.begin(): (await s.get(MediaAsset,asset_id)).storage_key=key.replace(str(UUID(a)),str(uuid4()))
    assert (await client.get('/api/v1/albums/'+a)).status_code==404
    assert (await client.post(access,json={'asset_ids':[str(asset_id)]},headers=headers(me))).status_code==404
    assert len(signing.reads)==calls

@pytest.mark.asyncio
async def test_remote_io_runs_without_album_lock_and_rechecks_deletion(client,db,remote):
    import asyncio
    import threading
    from datetime import datetime,timezone
    from backend.models import Album
    from sqlalchemy import select
    store,_=remote
    me,a,u,path=await reserved(client)
    entered=threading.Event(); release=threading.Event()
    original=store.read_bytes
    def slow_read(key):
        entered.set()
        assert release.wait(5)
        return original(key)
    store.read_bytes=slow_read
    request=asyncio.create_task(client.post(path,json={'sha256':hashlib.sha256(b'abcd').hexdigest()},headers=headers(me)))
    try:
        assert await asyncio.to_thread(entered.wait,5)
        async with asyncio.timeout(3):
            async with db() as s,s.begin():
                await s.scalar(select(Album).where(Album.id==UUID(a)).with_for_update())
                (await s.get(Page,UUID(u['page_id']))).removed_at=datetime.now(timezone.utc)
    finally: release.set()
    response=await request
    assert response.status_code==404

@pytest.mark.asyncio
async def test_complete_uses_one_authoritative_snapshot(client,db,remote):
    store,_=remote
    me,a,u,path=await reserved(client)
    def forbidden(*args): raise AssertionError('separate metadata/cache read')
    store.stat=forbidden; store.checksum=forbidden
    response=await client.post(path,json={'sha256':hashlib.sha256(b'abcd').hexdigest()},headers=headers(me))
    assert response.status_code==202
    assert store.calls==1
