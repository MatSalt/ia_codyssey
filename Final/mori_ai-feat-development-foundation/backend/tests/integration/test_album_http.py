"""Albums through real HTTP and PostgreSQL, sharing the auth HTTP fixture."""
import asyncio
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, func, update
from backend.models import Album, IdempotencyRecord, Outbox, Page, Run, Task
from backend.tests.integration.test_auth_http import client, login, ORIGIN


def headers(me, key='create-1'):
    return {'Origin': ORIGIN, 'X-CSRF-Token': me['csrf_token'], 'Idempotency-Key': key}


async def create(client, me, key='create-1'):
    return await client.post('/api/v1/albums', json={}, headers=headers(me, key))


@pytest.mark.asyncio
async def test_default_serialization_replay_and_version_priority(client, db):
    me = await login(client)
    first = await create(client, me)
    assert first.status_code == 201
    album = first.json()['data']['album']
    UUID(album['id'])
    assert album == {**album, 'title': '나의 사진첩', 'status': 'draft', 'version': 1,
                     'page_count': 0, 'cover': None, 'published_at': None}
    assert set(album) == {'id','title','status','version','page_count','cover','created_at','updated_at','published_at'}
    for field in ['created_at', 'updated_at']:
        assert datetime.fromisoformat(album[field].replace('Z', '+00:00')).utcoffset().total_seconds() == 0
    detail = await client.get('/api/v1/albums/' + album['id'])
    assert detail.json()['data'] == {'detail': {'album': album, 'order_mode': 'date', 'pages': [], 'active_run_id': None, 'generation_mode': None}, 'media_access': []}
    async with db() as s, s.begin():
        await s.execute(update(Album).values(version=2))
    replay = await create(client, me)
    assert replay.status_code == 201 and replay.json()['data'] == first.json()['data']
    assert replay.json()['request_id'] != first.json()['request_id']
    assert replay.headers['cache-control'] == 'no-store'
    assert replay.headers['x-request-id'] == replay.json()['request_id']


@pytest.mark.asyncio
async def test_required_key_strict_body_uuid_query_and_csrf(client):
    me = await login(client)
    h = headers(me)
    for body in [{'title':'x'}, {'extra':1}]:
        assert (await client.post('/api/v1/albums', json=body, headers=h)).status_code == 422
    for key in [None, '', ' ']:
        bad = {k:v for k,v in h.items() if k != 'Idempotency-Key'}
        if key is not None: bad['Idempotency-Key'] = key
        assert (await client.post('/api/v1/albums', json={}, headers=bad)).status_code == 422
    assert (await client.post('/api/v1/albums', json={}, headers={})).status_code == 403
    assert (await client.get('/api/v1/albums/not-uuid')).status_code == 422
    for query in ['limit=0', 'limit=51', 'limit=bad', 'cursor=bad', 'cursor=']:
        assert (await client.get('/api/v1/albums?' + query)).status_code == 422
    a = (await create(client, me)).json()['data']['album']['id']
    for query in ['', '?expected_version=0', '?expected_version=bad']:
        assert (await client.delete('/api/v1/albums/' + a + query, headers=h)).status_code == 422
    assert (await client.delete('/api/v1/albums/' + a + '?expected_version=1')).status_code == 403


@pytest.mark.asyncio
async def test_same_key_simultaneous_one_album_and_record(client, db):
    me = await login(client)
    a,b = await asyncio.wait_for(asyncio.gather(create(client, me), create(client, me)), 10)
    assert a.status_code == b.status_code == 201
    assert a.json()['data'] == b.json()['data']
    assert a.json()['request_id'] != b.json()['request_id']
    async with db() as s:
        assert await s.scalar(select(func.count()).select_from(Album)) == 1
        assert await s.scalar(select(func.count()).select_from(IdempotencyRecord)) == 1


@pytest.mark.asyncio
async def test_request_hash_conflict_and_owner_scope(client, db):
    me = await login(client)
    a = (await create(client, me)).json()['data']['album']['id']
    from backend.albums.service import create_album
    from backend.http.errors import APIError
    async with db() as s, s.begin():
        with pytest.raises(APIError) as exc:
            await create_album(s, UUID(me['user']['id']), 'create-1', 'a'*64)
        assert exc.value.status == 409 and exc.value.code == 'IDEMPOTENCY_CONFLICT'
    beta = await login(client, 'beta')
    assert (await client.get('/api/v1/albums/' + a)).status_code == 404
    assert (await client.delete('/api/v1/albums/' + a + '?expected_version=1', headers=headers(beta))).status_code == 404
    b = await create(client, beta)
    assert b.status_code == 201 and b.json()['data']['album']['id'] != a


@pytest.mark.asyncio
async def test_cursor_ties_pagination(client, db):
    me = await login(client)
    ids=[]
    for i in range(5):
        ids.append((await create(client, me, str(i))).json()['data']['album']['id'])
    async with db() as s, s.begin():
        await s.execute(update(Album).values(created_at=datetime(2026,1,1,tzinfo=timezone.utc)))
    found=[]; cursor=None
    for _ in range(3):
        r = await client.get('/api/v1/albums', params={'limit':2, **({'cursor':cursor} if cursor else {})})
        assert r.status_code == 200
        data=r.json()['data']; found += [a['id'] for a in data['items']]
        assert data['media_access'] == []
        cursor=data['next_cursor']
    assert found == sorted(ids, reverse=True) and cursor is None
    assert len((await client.get('/api/v1/albums')).json()['data']['items']) == 5


@pytest.mark.asyncio
async def test_delete_version_access_outbox_and_fence(client, db):
    me = await login(client)
    a = (await create(client, me)).json()['data']['album']['id']
    async with db() as s, s.begin():
        page=Page(album_id=UUID(a)); s.add(page); await s.flush()
        run=Run(album_id=UUID(a),status='running'); s.add(run); await s.flush()
        task=Task(run_id=run.id,page_id=page.id,stage='caption',status='running',fence_version=7,
                  lease_until=datetime(2099,1,1,tzinfo=timezone.utc)); s.add(task)
        await s.execute(update(Album).where(Album.id==UUID(a)).values(active_run_id=run.id,status='processing'))
    stale=await client.delete('/api/v1/albums/'+a+'?expected_version=2', headers=headers(me))
    assert stale.status_code == 409
    assert stale.json()['error']['code'] == 'VERSION_CONFLICT'
    assert stale.json()['error']['details'] == {'resource_type':'album','resource_id':a,'current_version':1}
    deleted=await client.delete('/api/v1/albums/'+a+'?expected_version=1', headers=headers(me))
    assert deleted.status_code == 202 and deleted.json()['data'] == {'album_id':a,'status':'deleted'}
    assert (await client.get('/api/v1/albums/'+a)).status_code == 404
    assert (await create(client, me)).status_code == 404
    assert (await client.delete('/api/v1/albums/'+a+'?expected_version=1',headers=headers(me))).status_code == 404
    assert (await client.get('/api/v1/albums')).json()['data']['items'] == []
    async with db() as s:
        row=await s.get(Album,UUID(a)); assert row.status=='deleted' and row.deleted_at and row.version==2
        run=await s.scalar(select(Run)); task=await s.scalar(select(Task))
        assert run.status=='cancelled' and run.finished_at
        assert task.status=='cancelled' and task.fence_version==8 and task.lease_until is None
        events=(await s.scalars(select(Outbox))).all()
        assert len(events)==1 and events[0].event_type=='album_cleanup' and events[0].entity_id==UUID(a)


@pytest.mark.asyncio
async def test_logout_unauthorized(client):
    assert (await client.get('/api/v1/albums')).status_code == 401
    me=await login(client)
    await client.post('/api/v1/auth/logout',json={},headers=headers(me))
    assert (await client.get('/api/v1/albums')).status_code==401
    assert (await create(client,me)).status_code==401
    assert (await client.get('/api/v1/albums/'+str(uuid4()))).status_code==401


@pytest.mark.asyncio
async def test_unknown_query_fields_rejected(client):
    me = await login(client)
    a = (await create(client, me)).json()['data']['album']['id']
    for path in ['/api/v1/albums?extra=1', '/api/v1/albums/'+a+'?extra=1']:
        assert (await client.get(path)).status_code == 422
    assert (await client.delete('/api/v1/albums/'+a+'?expected_version=1&extra=1',headers=headers(me))).status_code == 422


@pytest.mark.asyncio
async def test_two_connections_key_convergence_and_concurrent_delete(client, db):
    from sqlalchemy import text
    from backend.albums.service import create_album
    from backend.http.idempotency import request_hash
    me = await login(client)
    barrier=asyncio.Barrier(2)
    async def contender():
        async with db() as s, s.begin():
            pid=await s.scalar(text('SELECT pg_backend_pid()'))
            await barrier.wait()
            result=await create_album(s, UUID(me['user']['id']), 'parallel', request_hash({}))
            return pid, result
    a,b=await asyncio.wait_for(asyncio.gather(contender(),contender()),10)
    assert a[0] != b[0] and a[1] == b[1]
    album_id=a[1][1]['album']['id']
    async def delete():
        return await client.delete('/api/v1/albums/'+album_id+'?expected_version=1',headers=headers(me))
    deleted=await asyncio.wait_for(asyncio.gather(delete(),delete()),10)
    assert sorted(r.status_code for r in deleted)==[202,404]
    # Deleted lookup must precede hash comparison as well as replay.
    from backend.http.errors import APIError
    async with db() as s, s.begin():
        with pytest.raises(APIError) as exc:
            await create_album(s, UUID(me['user']['id']), 'parallel', 'b'*64)
        assert exc.value.status == 404
    async with db() as s:
        assert await s.scalar(select(func.count()).select_from(Album)) == 1
        assert await s.scalar(select(func.count()).select_from(IdempotencyRecord)) == 1
        assert await s.scalar(select(func.count()).select_from(Outbox)) == 1
