"""Generation HTTP and two-connection PostgreSQL admission contract."""
import asyncio
from datetime import datetime, timezone, timedelta
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select, func, text

from backend.main import create_app
from backend.models import Album, Page, MediaAsset, Upload, Run, Task, Outbox, Consent
from backend.tests.integration.test_auth_http import config, login, ORIGIN
from backend.tests.integration.test_album_http import create, headers
from backend.tests.integration.test_upload_http import consent


@pytest_asyncio.fixture
async def client(db):
    app = create_app(settings=config(dev_ai_enabled=True), session_factory=db)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as c:
            yield c


async def ready_album(client, db, *, count=1, agreed=True):
    me = await login(client)
    if agreed:
        await consent(client, me)
    album_id = UUID((await create(client, me, key=str(uuid4()))).json()['data']['album']['id'])
    async with db() as s, s.begin():
        album = await s.get(Album, album_id)
        for n in range(count):
            page = Page(album_id=album_id, position=n+1, selection_index=n+1, input_is_3_4=n%2 == 0)
            s.add(page); await s.flush()
            source = MediaAsset(owner_id=album.owner_id, album_id=album_id, page_id=page.id, role='source', storage_key=str(uuid4()), mime='image/png', bytes=100, status='ready', sha256='a'*64, width=30, height=40)
            normalized = MediaAsset(owner_id=album.owner_id, album_id=album_id, page_id=page.id, role='normalized', storage_key=str(uuid4()), mime='image/webp', bytes=80, status='ready', sha256='b'*64, width=30, height=40)
            s.add_all([source, normalized]); await s.flush()
            page.source_asset_id = source.id; page.normalized_asset_id = normalized.id
            s.add(Upload(album_id=album_id, page_id=page.id, asset_id=source.id, batch_id=uuid4(), client_file_id=uuid4(), declared_bytes=100, status='ready', expires_at=datetime.now(timezone.utc)+timedelta(seconds=900)))
    return me, str(album_id)


async def generate(client, me, album, version=1, key='generation'):
    return await client.post(f'/api/v1/albums/{album}/generation', json={'expected_version':version}, headers=headers(me,key))


async def resume(client, me, album, run, version, key='resume'):
    return await client.post(f'/api/v1/albums/{album}/generation/resume', json={'run_id':run, 'expected_version':version}, headers=headers(me,key))


@pytest.mark.asyncio
async def test_admission_atomic_snapshot_passthrough_replay(client, db):
    me, album = await ready_album(client, db, count=2)
    first = await generate(client, me, album)
    assert first.status_code == 202
    data = first.json()['data']
    assert data['album_version'] == 2 and data['status_url'] == f'/api/v1/albums/{album}/generation?run_id={data["run_id"]}'
    again = await generate(client, me, album)
    assert again.status_code == 202 and again.json()['data'] == data
    assert again.json()['request_id'] != first.json()['request_id']
    assert (await generate(client, me, album, version=2)).json()['error']['code'] == 'IDEMPOTENCY_CONFLICT'
    assert (await generate(client, me, album, version=2, key='other')).json()['error']['code'] == 'GENERATION_ALREADY_EXISTS'
    async with db() as s:
        run = await s.get(Run, UUID(data['run_id']))
        a = await s.get(Album, UUID(album))
        assert a.active_run_id == run.id and a.status == 'processing' and run.input_version == 1
        assert len(run.input_snapshot) == 2 and run.input_snapshot[0]['sha256'] == 'b'*64
        assert set(run.input_snapshot[0]) == {'page_id','position','normalized_asset_id','sha256','input_is_3_4'}
        assert [x['position'] for x in run.input_snapshot] == [1,2]
        assert run.config_snapshot['image_provider'] == run.config_snapshot['caption_provider'] == 'local_fake'
        assert run.config_snapshot['image_model'].startswith('fake-')
        tasks = (await s.scalars(select(Task).where(Task.run_id == run.id))).all()
        assert len(tasks) == 6
        portrait = next(t for t in tasks if str(t.page_id) == run.input_snapshot[0]['page_id'] and t.stage == 'image_transform')
        assert (portrait.status,portrait.completion_kind,portrait.requires_ai_call) == ('succeeded','passthrough',False)
        assert str(portrait.output_asset_id) == run.input_snapshot[0]['normalized_asset_id']
        assert await s.scalar(select(func.count()).select_from(Outbox).where(Outbox.event_type == 'task_ready')) == 5
    view = (await client.get(f'/api/v1/albums/{album}/generation')).json()['data']
    assert (view['total_pages'], view['completed_pages'], view['pending_pages'], view['progress_percent']) == (2,0,2,0)
    assert view['poll_after_ms'] == 3000 and not view['can_resume']
    assert first.headers['cache-control'] == 'no-store'


@pytest.mark.asyncio
async def test_validation_order_consent_ready_caps_version(client, db):
    me, album = await ready_album(client, db, agreed=False)
    assert (await generate(client, me, album, version=99)).json()['error']['code'] == 'CONSENT_REQUIRED'
    await consent(client, me)
    async with db() as s, s.begin():
        upload = await s.scalar(select(Upload)); upload.status = 'validating'
    r = await generate(client, me, album, version=99)
    assert r.status_code == 422 and r.json()['error']['code'] == 'UPLOAD_NOT_READY'
    async with db() as s, s.begin():
        (await s.scalar(select(Upload))).status = 'ready'
        (await s.scalar(select(Upload))).declared_bytes = 20971521
    assert (await generate(client, me, album, version=99)).json()['error']['code'] == 'FILE_TOO_LARGE'
    async with db() as s, s.begin():
        (await s.scalar(select(Upload))).declared_bytes = 100
    conflict = await generate(client, me, album, version=99)
    assert conflict.json()['error']['details'] == {'resource_type':'album','resource_id':album,'current_version':1}
    async with db() as s:
        assert await s.scalar(select(func.count()).select_from(Run)) == 0
        assert await s.scalar(select(func.count()).select_from(Task)) == 0


@pytest.mark.asyncio
async def test_owner_deleted_before_replay_and_get_run_scope(client, db):
    me, album = await ready_album(client, db)
    assert (await client.get(f'/api/v1/albums/{album}/generation')).json()['error']['code'] == 'GENERATION_NOT_FOUND'
    r = await generate(client, me, album); assert r.status_code == 202
    assert (await client.get(f'/api/v1/albums/{album}/generation?run_id={uuid4()}')).status_code == 404
    beta = await login(client, 'beta')
    assert (await generate(client, beta, album)).status_code == 404
    assert (await client.get(f'/api/v1/albums/{album}/generation')).status_code == 404
    me = await login(client)
    assert (await client.delete(f'/api/v1/albums/{album}?expected_version=2', headers=headers(me))).status_code == 202
    assert (await generate(client, me, album)).status_code == 404
    assert (await generate(client, me, album, version=99)).status_code == 404
    assert (await client.get(f'/api/v1/albums/{album}/generation')).status_code == 404


@pytest.mark.asyncio
async def test_two_albums_same_user_two_connections_and_action_required(client, db):
    from backend.generation.service import create_generation
    from backend.http.idempotency import request_hash
    from backend.http.errors import APIError
    me, a = await ready_album(client, db)
    me, b = await ready_album(client, db)
    barrier = asyncio.Barrier(2)
    async def contender(album):
        async with db() as s:
            try:
                async with s.begin():
                    pid = await s.scalar(text('SELECT pg_backend_pid()'))
                    await barrier.wait()
                    status,_ = await create_generation(s, UUID(me['user']['id']), UUID(album), 1, album, request_hash({'expected_version':1}), config(dev_ai_enabled=True))
                return pid,status
            except APIError as exc:
                return pid,exc.status
    results = await asyncio.wait_for(asyncio.gather(contender(a),contender(b)), 10)
    assert results[0][0] != results[1][0] and sorted(r[1] for r in results) == [202,429]
    async with db() as s, s.begin():
        run = await s.scalar(select(Run)); run.status = 'action_required'
        album = await s.get(Album,run.album_id); album.status = 'action_required'
        other = b if str(album.id) == a else a
    r = await generate(client, me, other)
    assert r.status_code == 429 and r.json()['error']['code'] == 'CONCURRENCY_LIMIT_EXCEEDED'


@pytest.mark.asyncio
async def test_same_key_concurrent_and_strict_boundary(client, db):
    me, album = await ready_album(client, db)
    left,right = await asyncio.gather(generate(client,me,album),generate(client,me,album))
    assert left.status_code == right.status_code == 202 and left.json()['data'] == right.json()['data']
    path = f'/api/v1/albums/{album}/generation'
    for version in [True, '2', 1.5, 0]:
        assert (await client.post(path,json={'expected_version':version},headers=headers(me,'bad'))).status_code == 422
    assert (await client.post(path,json={'expected_version':2,'extra':1},headers=headers(me))).status_code == 422
    assert (await client.post(path,json={'expected_version':2},headers={k:v for k,v in headers(me).items() if k != 'Idempotency-Key'})).status_code == 422
    assert (await client.post(path,json={'expected_version':2},headers={})).status_code == 403
    assert (await client.get(path+'?unknown=1')).status_code == 422
    async with db() as s:
        assert await s.scalar(select(func.count()).select_from(Run)) == 1


@pytest.mark.asyncio
async def test_resume_mixed_unknown_replay_version_and_safe_policy(client, db):
    me, album = await ready_album(client, db, count=2)
    data = (await generate(client,me,album)).json()['data']; run_id=data['run_id']
    async with db() as s, s.begin():
        (await s.get(Run,UUID(run_id))).status='action_required'
        (await s.get(Album,UUID(album))).status='action_required'
        tasks=(await s.scalars(select(Task).where(Task.run_id==UUID(run_id)))).all()
        snapshot=(await s.get(Run,UUID(run_id))).input_snapshot
        first_page=UUID(snapshot[0]['page_id'])
        unknown=next(t for t in tasks if t.stage=='caption' and t.page_id==first_page); unknown.status='unknown'
        local=next(t for t in tasks if t.stage=='optimize' and t.page_id==first_page); local.status='failed'; local.safe_to_retry=True
        local.requires_ai_call=False; local.has_persisted_input=True
        ai=next(t for t in tasks if t.stage=='image_transform' and t.status!='succeeded'); ai.status='failed'; ai.safe_to_retry=True
        local_id=local.id; unknown_id=unknown.id; ai_id=ai.id
    view=(await client.get(f'/api/v1/albums/{album}/generation')).json()['data']
    assert view['can_resume'] and view['unknown_pages']==1 and view['failed_pages']==1 and view['poll_after_ms'] is None
    r=await resume(client,me,album,run_id,1)
    assert r.json()['error']['code']=='VERSION_CONFLICT'
    first=await resume(client,me,album,run_id,2); assert first.status_code==202
    assert first.json()['data']['album_version']==2
    assert (await resume(client,me,album,run_id,2)).json()['data']==first.json()['data']
    assert (await resume(client,me,album,run_id,1)).json()['error']['code']=='IDEMPOTENCY_CONFLICT'
    async with db() as s:
        assert (await s.get(Task,local_id)).status=='queued'
        assert (await s.get(Task,unknown_id)).status=='unknown'
        assert (await s.get(Task,ai_id)).status=='failed'
        assert (await s.get(Run,UUID(run_id))).status=='action_required'
    view=(await client.get(f'/api/v1/albums/{album}/generation')).json()['data']
    assert view['poll_after_ms']==3000 and not view['can_resume']
    assert (await resume(client,me,album,run_id,2,key='new')).json()['error']['code']=='RESUME_NOT_ALLOWED'


@pytest.mark.asyncio
@pytest.mark.parametrize('count,source_bytes,want', [(0,100,'VALIDATION_ERROR'),(51,100,'PHOTO_COUNT_EXCEEDED'),(16,20971520,'ALBUM_BYTES_EXCEEDED')])
async def test_photo_and_byte_caps_are_atomic(client,db,count,source_bytes,want):
    me,album=await ready_album(client,db,count=count)
    async with db() as s,s.begin():
        for upload in (await s.scalars(select(Upload))).all():
            upload.declared_bytes=source_bytes
    r=await generate(client,me,album,version=99)
    assert r.json()['error']['code']==want
    async with db() as s:
        assert await s.scalar(select(func.count()).select_from(Run))==0
        assert (await s.get(Album,UUID(album))).status=='draft'


@pytest.mark.asyncio
async def test_fifty_photos_allowed_and_run_snapshots_immutable(client,db):
    me,album=await ready_album(client,db,count=50)
    first=await generate(client,me,album); assert first.status_code==202
    async with db() as s,s.begin():
        run=await s.get(Run,UUID(first.json()['data']['run_id']))
        saved_input=run.input_snapshot; saved_config=run.config_snapshot
        (await s.scalar(select(MediaAsset).where(MediaAsset.role=='normalized'))).sha256='c'*64
    assert (await generate(client,me,album)).json()['data']==first.json()['data']
    async with db() as s:
        run=await s.get(Run,UUID(first.json()['data']['run_id']))
        assert run.input_snapshot==saved_input and run.config_snapshot==saved_config
        assert await s.scalar(select(func.count()).select_from(Task))==150


@pytest.mark.asyncio
async def test_no_unknown_resume_new_version_consent_budget_and_success_preserved(client,db):
    me,album=await ready_album(client,db)
    first=await generate(client,me,album); run_id=first.json()['data']['run_id']
    async with db() as s,s.begin():
        run=await s.get(Run,UUID(run_id));run.status='action_required'
        (await s.get(Album,UUID(album))).status='action_required'
        tasks=(await s.scalars(select(Task).where(Task.run_id==run.id))).all()
        failed=next(t for t in tasks if t.stage=='caption'); failed.status='failed';failed.safe_to_retry=True
        failed.error_code='AI_TEMPORARY_FAILURE'; failed.attempt_count=450
        failed_id=failed.id
        succeeded=next(t for t in tasks if t.stage=='image_transform'); succeeded_id=succeeded.id
        (await s.scalar(select(Consent))).policy_version='old-policy'
    assert (await resume(client,me,album,run_id,2)).json()['error']['code']=='CONSENT_REQUIRED'
    await consent(client,me)
    assert (await resume(client,me,album,run_id,1)).json()['error']['code']=='VERSION_CONFLICT'
    r=await resume(client,me,album,run_id,2)
    assert r.status_code==429 and r.json()['error']['code']=='USAGE_LIMIT_EXCEEDED'
    view=(await client.get(f'/api/v1/albums/{album}/generation')).json()['data']
    assert not view['can_resume']
    async with db() as s,s.begin():
        (await s.get(Task,failed_id)).attempt_count=449
    first=await resume(client,me,album,run_id,2); assert first.status_code==202
    assert first.json()['data']['album_version']==3
    assert (await resume(client,me,album,run_id,2)).json()['data']==first.json()['data']
    async with db() as s:
        assert (await s.get(Task,failed_id)).status=='queued' and (await s.get(Task,failed_id)).error_code is None
        assert (await s.get(Task,succeeded_id)).status=='succeeded'
        assert (await s.get(Run,UUID(run_id))).status=='queued'
        assert (await s.get(Album,UUID(album))).status=='processing'
    assert (await resume(client,me,album,run_id,3,key='other')).json()['error']['code']=='RESUME_NOT_ALLOWED'


@pytest.mark.asyncio
async def test_unknown_reconciliation_same_attempt_and_local_persisted_only(client,db):
    from backend.models import Attempt,Job
    me,album=await ready_album(client,db)
    run_id=(await generate(client,me,album)).json()['data']['run_id']
    async with db() as s,s.begin():
        run=await s.get(Run,UUID(run_id));run.status='action_required'
        (await s.get(Album,UUID(album))).status='action_required'
        tasks=(await s.scalars(select(Task).where(Task.run_id==run.id))).all()
        unknown=next(t for t in tasks if t.stage=='caption'); unknown.status='unknown';unknown.attempt_count=1
        attempt=Attempt(task_id=unknown.id,attempt_no=1,fence_version=0,status='dispatching',dispatch_state='accepted_or_unknown')
        s.add(attempt);await s.flush(); attempt_id=attempt.id
        local=next(t for t in tasks if t.stage=='optimize'); local.status='failed';local.safe_to_retry=True;local.has_persisted_input=False
        local_id=local.id
    r=await resume(client,me,album,run_id,2)
    assert r.status_code==409 and r.json()['error']['code']=='RESUME_NOT_ALLOWED'
    async with db() as s,s.begin():
        (await s.get(Task,local_id)).has_persisted_input=True
    assert (await resume(client,me,album,run_id,2)).status_code==202
    assert (await resume(client,me,album,run_id,2)).status_code==202
    async with db() as s:
        jobs=(await s.scalars(select(Job).where(Job.kind=='reconcile_attempt'))).all()
        assert len(jobs)==1 and jobs[0].target_id==attempt_id
        assert await s.scalar(select(func.count()).select_from(Attempt))==1


@pytest.mark.asyncio
async def test_completed_counts_require_committed_assets_and_caption_and_reject_regeneration(client,db):
    me,album=await ready_album(client,db,count=4)
    run_id=(await generate(client,me,album)).json()['data']['run_id']
    async with db() as s,s.begin():
        run=await s.get(Run,UUID(run_id));run.status='action_required'
        a=await s.get(Album,UUID(album));a.status='action_required'
        pages=(await s.scalars(select(Page).where(Page.album_id==a.id).order_by(Page.position))).all()
        tasks=(await s.scalars(select(Task).where(Task.run_id==run.id))).all()
        for t in tasks:
            if t.page_id==pages[0].id:t.status='succeeded'
            elif t.page_id==pages[1].id:t.status='unknown' if t.stage=='caption' else 'failed'
            elif t.page_id==pages[2].id:t.status='failed'
        page=pages[0]; page.ai_caption='함께한 순간이 오래도록 마음에 남아요.';page.caption_text=''
        for role in ['result','thumbnail']:
            asset=MediaAsset(owner_id=a.owner_id,album_id=a.id,page_id=page.id,role=role,storage_key=str(uuid4()),mime='image/webp',bytes=10,status='ready',sha256='d'*64,width=30,height=40)
            s.add(asset);await s.flush();setattr(page,role+'_asset_id',asset.id)
    view=(await client.get(f'/api/v1/albums/{album}/generation')).json()['data']
    assert (view['total_pages'],view['completed_pages'],view['unknown_pages'],view['failed_pages'],view['pending_pages'],view['progress_percent'])==(4,1,1,1,1,25)
    async with db() as s,s.begin():
        (await s.get(Run,UUID(run_id))).status='succeeded'
        (await s.get(Album,UUID(album))).status='review_ready'
    view=(await client.get(f'/api/v1/albums/{album}/generation')).json()['data']
    assert view['poll_after_ms'] is None and not view['can_resume']
    assert (await generate(client,me,album,version=2,key='regenerate')).json()['error']['code']=='GENERATION_ALREADY_EXISTS'


@pytest.mark.asyncio
async def test_fake_disabled_config_and_http_gate(db):
    app=create_app(settings=config(),session_factory=db)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url=ORIGIN) as client:
            assert (await client.get('/api/dev/config')).json()['data']['dev_ai_enabled'] is False
            me,album=await ready_album(client,db)
            r=await generate(client,me,album)
            assert r.status_code==503 and r.json()['error']['retryable'] is False
            async with db() as s:
                assert await s.scalar(select(func.count()).select_from(Run))==0


@pytest.mark.asyncio
async def test_generation_uses_upload_accounting_without_source_bytes(client,db):
    me,album=await ready_album(client,db)
    async with db() as session,session.begin():
        source=await session.scalar(select(MediaAsset).where(MediaAsset.role=='source'))
        source.bytes=None; source.status='deleted'; source.deleted_at=datetime.now(timezone.utc)
    response=await generate(client,me,album)
    assert response.status_code==202, response.text
    async with db() as session:
        run=await session.scalar(select(Run))
        assert run.config_snapshot['normalized_webp_quality']==90


@pytest.mark.asyncio
async def test_generation_rejects_upload_with_mis_scoped_source_metadata(client,db):
    me,album=await ready_album(client,db)
    async with db() as session,session.begin():
        source=await session.scalar(select(MediaAsset).where(MediaAsset.role=='source'))
        source.role='transform_output'
    response=await generate(client,me,album)
    assert response.status_code==422 and response.json()['error']['code']=='UPLOAD_NOT_READY'
