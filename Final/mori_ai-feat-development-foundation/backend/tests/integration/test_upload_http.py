"""Private upload HTTP contract against PostgreSQL."""
from uuid import uuid4, UUID
import pytest
from sqlalchemy import select, func
from backend.models import Upload, Page, MediaAsset, Job
from backend.tests.integration.test_auth_http import client, login, ORIGIN
from backend.tests.integration.test_album_http import create, headers


def file(name='photo.png', size=100):
    return {'client_file_id':str(uuid4()), 'filename':name, 'bytes':size}


async def setup(client):
    me=await login(client)
    album=(await create(client,me)).json()['data']['album']['id']
    return me,album


async def consent(client,me):
    policy=(await client.get('/api/v1/me')).json()['data']['consent']['policy_version']
    r=await client.post('/api/v1/consents',json={'policy_version':policy,'purpose':'photo_upload_and_ai_processing','agreed':True},headers=headers(me))
    assert r.status_code in (200,201)


async def reserve(client,me,album,files=None,version=1,key='upload-1'):
    return await client.post(f'/api/v1/albums/{album}/uploads',json={'expected_version':version,'files':files or [file()]},headers=headers(me,key))


@pytest.mark.asyncio
async def test_consent_atomic_reservation_replay_and_strict(client,db):
    me,a=await setup(client)
    body=[file('IMG.HEIC')]
    r=await reserve(client,me,a,body)
    assert r.status_code==403 and r.json()['error']['code']=='CONSENT_REQUIRED'
    async with db() as s:
        for model in (Upload,Page,MediaAsset):
            assert await s.scalar(select(func.count()).select_from(model))==0
    await consent(client,me)
    r=await reserve(client,me,a,body)
    assert r.status_code==201
    data=r.json()['data']; u=data['uploads'][0]
    assert data['album_version']==2 and u['status']=='reserved' and u['method']=='PUT'
    assert set(u['required_headers'])=={'Content-Type'}
    replay=await reserve(client,me,a,body)
    assert replay.status_code==201 and replay.json()['data']==data
    assert replay.json()['request_id']!=r.json()['request_id']
    assert (await reserve(client,me,a,[file()],key='upload-1')).status_code==409
    assert (await reserve(client,me,a,[file('x.gif')],version=2,key='bad')).status_code==422
    assert (await reserve(client,me,a,[file(size=20971521)],version=2,key='large')).status_code==413


@pytest.mark.asyncio
async def test_put_complete_private_owner_and_size(client,db):
    me,a=await setup(client); await consent(client,me)
    r=await reserve(client,me,a,[file(size=4)])
    assert r.status_code==201
    u=r.json()['data']['uploads'][0]; h={**u['required_headers'],**headers(me)}
    assert (await client.put(u['upload_url'],content=b'bad',headers=h)).status_code==422
    assert (await client.put(u['upload_url'],content=b'abcd',headers=h)).status_code==204
    assert (await client.put(u['upload_url'],content=b'xxxx',headers=h)).status_code==409
    path=f'/api/v1/albums/{a}/uploads/{u["upload_id"]}'
    first=await client.post(path+'/complete',json={},headers=headers(me))
    assert first.status_code==202 and first.json()['data']['status']=='validating'
    assert (await client.post(path+'/complete',json={},headers=headers(me))).status_code==202
    async with db() as s:
        assert await s.scalar(select(func.count()).select_from(Job))==1
    beta=await login(client,'beta')
    assert (await client.get(path)).status_code==404
    assert (await client.put(u['upload_url'],content=b'abcd',headers={**h,'X-CSRF-Token':beta['csrf_token']})).status_code==404


@pytest.mark.asyncio
async def test_counts_bytes_concurrency_expiry_and_removed_slots(client,db):
    import asyncio
    from datetime import datetime, timezone, timedelta
    from sqlalchemy import update
    from backend.models import Album
    me,a=await setup(client); await consent(client,me)
    # 15 * 20MiB == 300MiB, exactly accepted; a further byte is refused.
    files=[file(size=20971520) for _ in range(15)]
    r=await reserve(client,me,a,files); assert r.status_code==201
    assert (await reserve(client,me,a,[file(size=1)],version=2,key='over')).json()['error']['code']=='ALBUM_BYTES_EXCEEDED'
    async with db() as s,s.begin():
        await s.execute(update(Upload).values(expires_at=datetime.now(timezone.utc)-timedelta(seconds=1)))
    # Expired uploads release bytes while continuing to occupy 15 slots.
    r=await reserve(client,me,a,[file(size=1) for _ in range(35)],version=2,key='fill')
    assert r.status_code==201
    assert (await reserve(client,me,a,[file(size=1)],version=3,key='51')).json()['error']['code']=='PHOTO_COUNT_EXCEEDED'
    first=r.json()['data']['uploads'][0]
    deleted=await client.delete(f'/api/v1/albums/{a}/pages/{first["page_id"]}?expected_version=3',headers=headers(me))
    assert deleted.status_code==200
    parallel=await asyncio.gather(reserve(client,me,a,[file(size=1)],version=4,key='race1'),reserve(client,me,a,[file(size=1)],version=4,key='race2'))
    assert sorted(x.status_code for x in parallel)==[201,409]
    async with db() as s:
        assert await s.scalar(select(func.count()).select_from(Page).where(Page.removed_at.is_(None)))==50


@pytest.mark.asyncio
async def test_private_no_cookie_expiry_header_path_and_storage(client,db,tmp_path):
    import httpx
    from backend.storage.local import LocalStorage
    me,a=await setup(client); await consent(client,me)
    u=(await reserve(client,me,a,[file(size=4)])).json()['data']['uploads'][0]
    h={**u['required_headers'],**headers(me)}
    url=u['upload_url']
    assert (await client.put(url.replace('expires=','expires=1'),content=b'abcd',headers=h)).status_code==404
    assert (await client.put(url.replace(u['upload_id'],str(uuid4())),content=b'abcd',headers=h)).status_code==404
    assert (await client.put(url,content=b'abcd',headers={**h,'Content-Type':'image/jpeg'})).status_code==422
    cookies=dict(client.cookies); client.cookies.clear()
    assert (await client.put(url,content=b'abcd',headers=h)).status_code==404
    client.cookies.update(cookies)
    store=LocalStorage(tmp_path/'private')
    for key in ['../../escape',str(uuid4()),'/absolute','a/b/c/source']:
        with pytest.raises(ValueError): store.path(key)
    owner=str(uuid4());album=str(uuid4());page=str(uuid4())
    (store.root/owner).symlink_to(tmp_path,target_is_directory=True)
    with pytest.raises(ValueError): store.path(f'{owner}/{album}/{page}/source',create=True)


@pytest.mark.asyncio
async def test_exact_expiry_and_strict_order_manual_appends(client,db):
    from datetime import datetime,timezone,timedelta
    from sqlalchemy import update
    me,a=await setup(client); await consent(client,me)
    data=(await reserve(client,me,a,[file(size=1),file(size=1)])).json()['data']
    ids=[u['page_id'] for u in data['uploads']]
    path=f'/api/v1/albums/{a}/page-order'
    for bad in [ids[:1],ids+ids[:1],[ids[0],ids[0]]]:
        assert (await client.put(path,json={'expected_version':2,'page_ids':bad},headers=headers(me))).status_code==422
    r=await client.put(path,json={'expected_version':2,'page_ids':list(reversed(ids))},headers=headers(me))
    assert r.status_code==200 and r.json()['data']['detail']['order_mode']=='manual'
    more=await reserve(client,me,a,[file(size=1)],version=3,key='append'); assert more.status_code==201
    detail=(await client.get('/api/v1/albums/'+a)).json()['data']['detail']
    assert [p['id'] for p in detail['pages']][:2]==list(reversed(ids))
    u=data['uploads'][0]
    async with db() as s,s.begin():
        await s.execute(update(Upload).where(Upload.id==UUID(u['upload_id'])).values(expires_at=datetime.now(timezone.utc)-timedelta(seconds=1)))
    expired=await client.post(f'/api/v1/albums/{a}/uploads/{u["upload_id"]}/complete',json={},headers=headers(me))
    assert expired.status_code==200 and expired.json()['data']['status']=='expired'


def test_signing_key_concurrent_atomic_and_symlink(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from backend.storage.signing import Signer
    root=tmp_path/'keys'; root.mkdir()
    with ThreadPoolExecutor(max_workers=12) as pool:
        keys=list(pool.map(lambda _:Signer(root).key,range(24)))
    assert len(set(keys))==1 and len(keys[0])==32
    path=root/'.capability-key'; path.unlink();path.symlink_to(tmp_path/'other')
    with pytest.raises(OSError): Signer(root)
    path.unlink();path.write_bytes(b'partial')
    with pytest.raises(ValueError): Signer(root)


@pytest.mark.asyncio
async def test_bounded_stream_exact_max_nooverwrite_and_temp_cleanup(tmp_path):
    from backend.storage.local import LocalStorage,storage_key
    store=LocalStorage(tmp_path/'media')
    key=storage_key(uuid4(),uuid4(),uuid4(),'source')
    async def chunks(count):
        for _ in range(count): yield b'x'*65536
    await store.put_stream(key,chunks(320),20971520)
    assert store.stat(key).st_size==20971520
    checksum=store.checksum(key)
    assert await store.put_stream(key,chunks(320),20971520) is False
    assert store.checksum(key)==checksum
    key2=storage_key(uuid4(),uuid4(),uuid4(),'source')
    with pytest.raises(ValueError): await store.put_stream(key2,chunks(321),20971520)
    assert not store.path(key2).exists()
    assert not list(store.root.rglob('.put-*'))


@pytest.mark.asyncio
async def test_concurrent_put_and_complete_converge(client,db):
    import asyncio
    me,a=await setup(client); await consent(client,me)
    u=(await reserve(client,me,a,[file(size=4)])).json()['data']['uploads'][0]
    h={**u['required_headers'],**headers(me)}
    results=await asyncio.gather(client.put(u['upload_url'],content=b'abcd',headers=h),client.put(u['upload_url'],content=b'abcd',headers=h))
    assert sorted(r.status_code for r in results)==[204,204]
    url=f'/api/v1/albums/{a}/uploads/{u["upload_id"]}/complete'
    results=await asyncio.gather(client.post(url,json={},headers=headers(me)),client.post(url,json={},headers=headers(me)))
    assert [r.status_code for r in results]==[202,202]
    async with db() as s: assert await s.scalar(select(func.count()).select_from(Job))==1


@pytest.mark.asyncio
async def test_same_key_concurrent_reservation_and_strict_inputs(client,db):
    import asyncio
    me,a=await setup(client);await consent(client,me)
    files=[{**file('photo.heic'),'mime':'application/octet-stream'}]
    left,right=await asyncio.gather(reserve(client,me,a,files),reserve(client,me,a,files))
    assert left.status_code==right.status_code==201 and left.json()['data']==right.json()['data']
    assert left.json()['request_id']!=right.json()['request_id']
    async with db() as s:
        assert await s.scalar(select(func.count()).select_from(Upload))==1
    for bad in [True,1.5,'1',0,-1]:
        f=file();f['bytes']=bad
        assert (await reserve(client,me,a,[f],version=2,key=str(bad))).status_code==422
    body={'expected_version':2,'files':[file()],'extra':1}
    assert (await client.post(f'/api/v1/albums/{a}/uploads',json=body,headers=headers(me,'extra'))).status_code==422
    assert (await client.post(f'/api/v1/albums/{a}/uploads',json={'expected_version':2,'files':[file()]},headers={**headers(me),'Idempotency-Key':''})).status_code==422


@pytest.mark.asyncio
async def test_same_owner_relogin_put_retry_new_csrf_and_immutable(client,db):
    me,a=await setup(client);await consent(client,me)
    u=(await reserve(client,me,a,[file(size=4)])).json()['data']['uploads'][0]
    h={**u['required_headers'],**headers(me)}
    assert (await client.put(u['upload_url'],content=b'abcd',headers=h)).status_code==204
    newer=await login(client,'alpha')
    assert newer['csrf_token']!=me['csrf_token']
    assert (await client.put(u['upload_url'],content=b'abcd',headers=h)).status_code==403
    h={**u['required_headers'],**headers(newer)}
    assert (await client.put(u['upload_url'],content=b'abcd',headers=h)).status_code==204
    assert (await client.put(u['upload_url'],content=b'xxxx',headers=h)).status_code==409
    from backend.storage.local import LocalStorage
    from backend.tests.integration.test_auth_http import config
    async with db() as s: asset=await s.get(MediaAsset,UUID(u['asset_id']))
    assert LocalStorage(config().storage_root).path(asset.storage_key).read_bytes()==b'abcd'


@pytest.mark.asyncio
async def test_page_order_versions_only_change_for_real_public_changes(client, db):
    me, album = await setup(client)
    await consent(client, me)
    entries = (await reserve(client, me, album, [file(size=1) for _ in range(3)])).json()['data']['uploads']
    ids = [entry['page_id'] for entry in entries]
    path = f'/api/v1/albums/{album}/page-order'
    first = await client.put(path, json={'page_ids': [ids[1], ids[0], ids[2]], 'expected_version': 2}, headers=headers(me))
    assert first.status_code == 200
    detail = first.json()['data']['detail']
    assert detail['album']['version'] == 3 and detail['order_mode'] == 'manual'
    assert [page['version'] for page in detail['pages']] == [2, 2, 1]
    repeated = await client.put(path, json={'page_ids': [ids[1], ids[0], ids[2]], 'expected_version': 3}, headers=headers(me))
    assert repeated.status_code == 200 and repeated.json()['data']['detail'] == detail
    assert (await client.get('/api/v1/albums/' + album)).json()['data']['detail'] == detail
    removed = await client.delete(f'/api/v1/albums/{album}/pages/{ids[1]}?expected_version=3', headers=headers(me))
    assert removed.status_code == 200
    after = removed.json()['data']['detail']
    assert after['album']['version'] == 4
    assert [page['id'] for page in after['pages']] == [ids[0], ids[2]]
    assert [page['version'] for page in after['pages']] == [3, 2]


@pytest.mark.asyncio
async def test_expiry_and_complete_versions_are_atomic_and_terminal_replay_is_noop(client, db):
    from datetime import datetime, timezone, timedelta
    me, album = await setup(client)
    await consent(client, me)
    entry = (await reserve(client, me, album, [file(size=4)])).json()['data']['uploads'][0]
    async with db() as session, session.begin():
        (await session.get(Upload, UUID(entry['upload_id']))).expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    path = f'/api/v1/albums/{album}/uploads/{entry["upload_id"]}'
    expired = await client.get(path)
    assert expired.json()['data']['status'] == 'expired' and expired.json()['data']['album_version'] == 3
    detail = (await client.get('/api/v1/albums/' + album)).json()['data']['detail']
    assert detail['pages'][0]['version'] == 2
    assert (await client.get(path)).json()['data'] == expired.json()['data']
    assert (await client.post(path + '/complete', json={}, headers=headers(me))).json()['data'] == expired.json()['data']
    assert (await client.get('/api/v1/albums/' + album)).json()['data']['detail'] == detail
