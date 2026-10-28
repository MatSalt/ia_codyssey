"""Caption/review/viewer public HTTP contracts with real PG and private WebP."""
import asyncio
from datetime import datetime,timezone,timedelta
from uuid import UUID,uuid4
import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select,func,text

from backend.main import create_app
from backend.models import Album,Page,Run,Task,Attempt,MediaAsset,Consent
from backend.tests.integration.test_auth_http import config,login,ORIGIN
from backend.tests.integration.test_album_http import headers
from backend.tests.integration.test_generation_pipeline import pipeline,drain


@pytest_asyncio.fixture
async def client(db,tmp_path):
    app=create_app(settings=config(dev_ai_enabled=True,storage_root=tmp_path/'private'),session_factory=db)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url=ORIGIN) as c:yield c


async def review(client,db,tmp_path,count=2):
    me,album,run_id,store,executor,runner=await pipeline(client,db,tmp_path,count=count)
    await drain(runner)
    data=(await client.get('/api/v1/albums/'+album)).json()['data']['detail']
    assert data['album']['status']=='review_ready'
    return me,album,data,store


async def save(client,me,album,page,version,text):
    return await client.patch(f'/api/v1/albums/{album}/pages/{page}/caption',json={'expected_version':version,'caption_text':text},headers=headers(me))


async def publish(client,me,album,version):
    return await client.post(f'/api/v1/albums/{album}/publish',json={'expected_version':version},headers=headers(me))


@pytest.mark.asyncio
async def test_caption_nfc_unicode_empty_noop_and_strict_stale_version(client,db,tmp_path):
    me,album,detail,store=await review(client,db,tmp_path,count=1)
    page=detail['pages'][0];version=page['version'];album_version=detail['album']['version']
    r=await save(client,me,album,page['id'],version,'가'*40+'🙂'*40)
    assert r.status_code==200
    data=r.json()['data']
    assert data['page']['caption_text']=='가'*40+'🙂'*40 and data['page']['version']==version+1
    assert data['album_version']==album_version+1
    assert set(data)=={'page','album_version'} and set(data['page'])==set(page)
    assert data['page']['source'] is None and 'ai_caption' not in data['page']
    assert r.headers['cache-control']=='no-store'
    same=await save(client,me,album,page['id'],version+1,'가'*40+'🙂'*40)
    assert same.status_code==200 and same.json()['data']==data
    assert same.json()['request_id']!=r.json()['request_id']
    lost=await save(client,me,album,page['id'],version,'가'*40+'🙂'*40)
    assert lost.status_code==409 and lost.json()['error']['details']=={'resource_type':'page','resource_id':page['id'],'current_version':version+1}
    long=await save(client,me,album,page['id'],version+1,'🙂'*81)
    assert long.status_code==422 and long.json()['error']['code']=='CAPTION_TOO_LONG'
    decomposed=await save(client,me,album,page['id'],version+1,'가'*81)
    assert decomposed.status_code==422 and decomposed.json()['error']['code']=='CAPTION_TOO_LONG'
    async with db() as s,s.begin():
        (await s.scalar(select(Consent))).policy_version='previous-policy'
    empty=await save(client,me,album,page['id'],version+1,'')
    assert empty.status_code==200 and empty.json()['data']['page']['caption_text']==''
    assert (await publish(client,me,album,empty.json()['data']['album_version'])).status_code==200
    assert (await client.get(f'/api/v1/albums/{album}/viewer')).json()['data']['pages'][0]['caption_text']==''
    async with db() as s:
        saved=await s.get(Page,UUID(page['id']))
        assert saved.ai_caption=='함께한 순간이 오래도록 마음에 남아요.' and saved.caption_edited_at is not None
        assert await s.scalar(select(func.count()).select_from(Attempt))==2


@pytest.mark.asyncio
async def test_different_pages_parallel_edits_and_same_page_conflict(client,db,tmp_path):
    me,album,detail,store=await review(client,db,tmp_path)
    a,b=detail['pages']
    responses=await asyncio.gather(save(client,me,album,a['id'],a['version'],'첫 글귀'),save(client,me,album,b['id'],b['version'],'둘째 글귀'))
    assert [r.status_code for r in responses]==[200,200]
    v=responses[0].json()['data']['page']['version']
    responses=await asyncio.gather(save(client,me,album,a['id'],v,'경쟁 A'),save(client,me,album,a['id'],v,'경쟁 B'))
    assert sorted(r.status_code for r in responses)==[200,409]
    async with db() as s:
        assert (await s.get(Album,UUID(album))).version==detail['album']['version']+3
        assert (await s.get(Page,UUID(b['id']))).caption_text=='둘째 글귀'


@pytest.mark.asyncio
async def test_publish_rechecks_ready_and_version_then_replays_current_published(client,db,tmp_path):
    me,album,detail,store=await review(client,db,tmp_path,count=1)
    version=detail['album']['version'];page=detail['pages'][0]
    conflict=await publish(client,me,album,version-1)
    assert conflict.status_code==409 and conflict.json()['error']['details']=={'resource_type':'album','resource_id':album,'current_version':version}
    async with db() as s,s.begin():
        asset=await s.get(MediaAsset,UUID(page['result']['asset_id']));asset.status='pending'
    r=await publish(client,me,album,version)
    assert r.status_code==409 and r.json()['error']['code']=='STATE_CONFLICT'
    async with db() as s,s.begin():
        (await s.get(MediaAsset,UUID(page['result']['asset_id']))).status='ready'
    first=await publish(client,me,album,version)
    assert first.status_code==200
    data=first.json()['data'];assert data['album']['status']=='published' and data['album']['version']==version+1
    timestamp=data['album']['published_at'];assert timestamp is not None
    assert (await publish(client,me,album,version)).status_code==409
    same=await publish(client,me,album,version+1)
    assert same.status_code==200 and same.json()['data']==data
    changed=await save(client,me,album,page['id'],page['version'],'완성 뒤 수정')
    assert changed.status_code==200
    latest=(await client.get('/api/v1/albums/'+album)).json()['data']['detail']
    assert latest['album']['status']=='published' and latest['album']['published_at']==timestamp


@pytest.mark.asyncio
async def test_viewer_exact_dto_first_two_urls_and_private_expiry(client,db,tmp_path,monkeypatch):
    from backend.albums import music
    soundtrack=tmp_path/'bgm.mp3';soundtrack.write_bytes(b'ID3'+b'x'*100)
    monkeypatch.setattr(music,'BGM_PATH',soundtrack)
    from backend.storage.signing import Signer
    me,album,detail,store=await review(client,db,tmp_path,count=3)
    assert (await client.get(f'/api/v1/albums/{album}/viewer')).status_code==409
    published=await publish(client,me,album,detail['album']['version']);assert published.status_code==200
    r=await client.get(f'/api/v1/albums/{album}/viewer');assert r.status_code==200
    view=r.json()['data']
    assert set(view)=={'album_id','title','version','pages','media_access','music','generation_mode'}
    assert view['music']=={'track_id':'mori-bgm-v1','title':'사진첩 배경음악','url':'/audio/bgm.mp3'}
    assert (await client.get(view['music']['url'],headers={'Range':'bytes=0-2'})).status_code==206
    assert [p['position'] for p in view['pages']]==[1,2,3]
    assert [p['id'] for p in view['pages']]==[p['id'] for p in detail['pages']]
    for page in view['pages']:
        assert set(page)=={'id','position','image','caption_text'}
        assert page['image']['mime']=='image/webp' and page['image']['width']*4==page['image']['height']*3
    assert [a['asset_id'] for a in view['media_access']]==[p['image']['asset_id'] for p in view['pages'][:2]]
    for access in view['media_access']:
        image=await client.get(access['url']);assert image.status_code==200 and image.headers['content-type']=='image/webp'
    third=view['pages'][2]['image']['asset_id']
    access=await client.post(f'/api/v1/albums/{album}/media-access',json={'asset_ids':[third]},headers=headers(me))
    assert access.status_code==200 and (await client.get(access.json()['data']['media_access'][0]['url'])).status_code==200
    first=view['media_access'][0];path=f'/api/v1/private/albums/{album}/media/{first["asset_id"]}'
    expired=Signer(store.root).url('GET',path,first['asset_id'],int(datetime.now(timezone.utc).timestamp())-1,'image/webp')
    assert (await client.get(expired)).status_code==404
    reissue=await client.post(f'/api/v1/albums/{album}/media-access',json={'asset_ids':[first['asset_id']]},headers=headers(me))
    assert reissue.status_code==200 and (await client.get(reissue.json()['data']['media_access'][0]['url'])).status_code==200
    assert (await client.get(f'/api/v1/albums/{album}/viewer')).json()['data']['version']==view['version']
    async with db() as s:
        inputs=(await s.scalars(select(MediaAsset).where(MediaAsset.role.in_(['source','normalized','transform_output'])))).all()
    for asset in inputs:
        assert (await client.post(f'/api/v1/albums/{album}/media-access',json={'asset_ids':[str(asset.id)]},headers=headers(me))).status_code==404


@pytest.mark.asyncio
async def test_owner_deleted_logout_and_strict_http_boundary(client,db,tmp_path):
    me,album,detail,store=await review(client,db,tmp_path,count=1)
    page=detail['pages'][0]
    path=f'/api/v1/albums/{album}/pages/{page["id"]}/caption'
    for body in [{'expected_version':True,'caption_text':'x'},{'expected_version':page['version'],'caption_text':None},{'expected_version':page['version'],'caption_text':'x','extra':True}]:
        assert (await client.patch(path,json=body,headers=headers(me))).status_code==422
    assert (await client.patch(path,json={'expected_version':page['version'],'caption_text':'x'},headers={})).status_code==403
    assert (await client.get(f'/api/v1/albums/{album}/viewer?extra=1')).status_code==422
    for body in [{'expected_version':True},{'expected_version':detail['album']['version'],'extra':1}]:
        assert (await client.post(f'/api/v1/albums/{album}/publish',json=body,headers=headers(me))).status_code==422
    assert (await client.patch(path+'?extra=1',json={'expected_version':page['version'],'caption_text':'x'},headers=headers(me))).status_code==422
    assert (await publish(client,me,album,detail['album']['version'])).status_code==200
    view=(await client.get(f'/api/v1/albums/{album}/viewer')).json()['data'];url=view['media_access'][0]['url']
    beta=await login(client,'beta')
    assert (await save(client,beta,album,page['id'],page['version'],'x')).status_code==404
    assert (await publish(client,beta,album,view['version'])).status_code==404
    assert (await client.get(f'/api/v1/albums/{album}/viewer')).status_code==404
    assert (await client.get(url)).status_code==404
    me=await login(client)
    assert (await client.post('/api/v1/auth/logout',json={},headers=headers(me))).status_code==204
    assert (await client.get(f'/api/v1/albums/{album}/viewer')).status_code==401
    assert (await client.get(url)).status_code==404
    me=await login(client)
    assert (await client.delete(f'/api/v1/albums/{album}?expected_version={view["version"]}',headers=headers(me))).status_code==202
    assert (await save(client,me,album,page['id'],999,'x')).status_code==404
    assert (await publish(client,me,album,999)).status_code==404
    assert (await client.get(f'/api/v1/albums/{album}/viewer')).status_code==404
    assert (await client.get(url)).status_code==404


@pytest.mark.asyncio
@pytest.mark.parametrize('status',['draft','processing','action_required'])
async def test_nonreview_state_blocks_edit_publish_and_viewer(client,db,tmp_path,status):
    me,album,detail,store=await review(client,db,tmp_path,count=1)
    async with db() as s,s.begin():
        (await s.get(Album,UUID(album))).status=status
    page=detail['pages'][0]
    assert (await save(client,me,album,page['id'],page['version'],'x')).status_code==409
    assert (await publish(client,me,album,detail['album']['version'])).status_code==409
    assert (await client.get(f'/api/v1/albums/{album}/viewer')).status_code==409


@pytest.mark.asyncio
async def test_publish_save_two_connections_are_atomic_and_page_versions_independent(client,db,tmp_path):
    from backend.albums.editing import save_caption,publish_album
    from sqlalchemy.ext.asyncio import AsyncSession
    me,album,detail,store=await review(client,db,tmp_path,count=1)
    page=detail['pages'][0];barrier=asyncio.Barrier(2)
    async def contender(kind):
        from backend.http.errors import APIError
        async with db.kw['bind'].connect() as conn:
            pid=await conn.scalar(text('SELECT pg_backend_pid()'));await conn.rollback()
            await barrier.wait()
            async with AsyncSession(bind=conn,expire_on_commit=False) as s:
                try:
                    async with s.begin():
                        if kind=='save':result=await save_caption(s,UUID(me['user']['id']),UUID(album),UUID(page['id']),page['version'],'동시에 저장한 글귀')
                        else:result=await publish_album(s,UUID(me['user']['id']),UUID(album),detail['album']['version'])
                    return pid,200,result
                except APIError as exc:return pid,exc.status,None
    saved,published=await asyncio.wait_for(asyncio.gather(contender('save'),contender('publish')),10)
    assert saved[0]!=published[0] and saved[1]==200 and published[1] in {200,409}
    latest=(await client.get('/api/v1/albums/'+album)).json()['data']['detail']
    assert latest['pages'][0]['caption_text']=='동시에 저장한 글귀'
    if published[1]==409:
        assert latest['album']['status']=='review_ready'
        assert (await publish(client,me,album,latest['album']['version'])).status_code==200
    else:assert latest['album']['status']=='published'


@pytest.mark.asyncio
@pytest.mark.parametrize('text',['\x00','\ud800'])
async def test_invalid_database_unicode_is_rejected_without_public_mutation(client,db,tmp_path,text):
    import json
    me,album,detail,store=await review(client,db,tmp_path,count=1)
    page=detail['pages'][0]
    r=await client.patch(f'/api/v1/albums/{album}/pages/{page["id"]}/caption',
        content=json.dumps({'caption_text':text,'expected_version':page['version']},ensure_ascii=True).encode(),
        headers={**headers(me),'Content-Type':'application/json'})
    assert r.status_code==422 and r.json()['error']['code']=='VALIDATION_ERROR'
    async with db() as s:
        saved=await s.get(Page,UUID(page['id']))
        assert saved.version==page['version'] and saved.caption_text==page['caption_text']


@pytest.mark.asyncio
@pytest.mark.parametrize('damage',['owner','page','role','mime','ratio','thumbnail_deleted','caption_missing','ai_blank','key'])
async def test_publish_and_viewer_reject_unready_or_out_of_scope_outputs(client,db,tmp_path,damage):
    from backend.models import User
    me,album,detail,store=await review(client,db,tmp_path,count=2)
    version=detail['album']['version']
    async with db() as s,s.begin():
        page=await s.get(Page,UUID(detail['pages'][0]['id']))
        asset=await s.get(MediaAsset,page.result_asset_id)
        if damage=='owner':
            user=User();s.add(user);await s.flush();asset.owner_id=user.id
        elif damage=='page':asset.page_id=UUID(detail['pages'][1]['id'])
        elif damage=='role':asset.role='normalized'
        elif damage=='mime':asset.mime='image/png'
        elif damage=='ratio':asset.width+=1
        elif damage=='thumbnail_deleted':(await s.get(MediaAsset,page.thumbnail_asset_id)).deleted_at=datetime.now(timezone.utc)
        elif damage=='caption_missing':page.caption_text=None
        elif damage=='ai_blank':page.ai_caption='  '
        elif damage=='key':asset.storage_key=str(uuid4())
    r=await publish(client,me,album,version)
    assert r.status_code==409 and r.json()['error']['code']=='STATE_CONFLICT'
    async with db() as s,s.begin():
        a=await s.get(Album,UUID(album));assert a.version==version and a.status=='review_ready'
        a.status='published'
    assert (await client.get(f'/api/v1/albums/{album}/viewer')).status_code==409

@pytest.mark.asyncio
async def test_generation_provenance_survives_current_mode_switch(client,db,tmp_path):
    me,album,detail,store=await review(client,db,tmp_path,count=1)
    assert detail['generation_mode']=='local_fake'
    progress=(await client.get(f'/api/v1/albums/{album}/generation')).json()['data']
    assert progress['generation_mode']=='local_fake'
    assert (await publish(client,me,album,detail['album']['version'])).status_code==200
    real_settings=config(dev_ai_enabled=False,ai_real_calls_enabled=True,openai_api_key='test-only',storage_root=tmp_path/'private')
    app=create_app(settings=real_settings,session_factory=db)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url=ORIGIN,cookies=client.cookies) as switched:
            assert (await switched.get('/api/dev/config')).json()['data']['generation_mode']=='openai'
            assert (await switched.get(f'/api/v1/albums/{album}')).json()['data']['detail']['generation_mode']=='local_fake'
            assert (await switched.get(f'/api/v1/albums/{album}/viewer')).json()['data']['generation_mode']=='local_fake'
