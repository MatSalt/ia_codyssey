"""Untrusted browser metadata is checked against independently decoded input."""
from io import BytesIO
from uuid import UUID

import pytest
from PIL import Image
from sqlalchemy import select
from backend.models import Upload, Page
from backend.tests.integration.test_auth_http import client, config
from backend.tests.integration.test_album_http import headers
from backend.tests.integration.test_upload_http import setup, consent, reserve, file
from backend.uploads.validation import ValidationWorker


def hint(**overrides):
    return dict(version=1, original_width=300, original_height=400,
                captured_at_raw='2020:01:02 03:04:05', captured_timezone='+09:00', **overrides)


@pytest.mark.asyncio
async def test_preprocessing_snapshot_and_quality(client, db):
    me, album = await setup(client); await consent(client, me)
    response = await reserve(client, me, album, [{**file('x.webp'), 'preprocessing': hint()}])
    assert response.status_code == 201, response.text
    async with db() as session:
        upload = await session.scalar(select(Upload))
        assert upload.validation_config['preprocessing'] == hint()
        assert upload.validation_config['media']['NORMALIZED_WEBP_QUALITY'] == 90
        assert upload.validation_config['media']['NORMALIZATION_VERSION'] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('patch', [dict(version=True), dict(version=2), dict(original_width='300'),
    dict(original_width=True), dict(original_height=0), dict(original_width=8000, original_height=5001),
    dict(captured_at_raw=123), dict(captured_at_raw='x'*257), dict(captured_timezone='x'*65), dict(extra=True)])
async def test_invalid_preprocessing_is_atomic(client, db, patch):
    me, album = await setup(client); await consent(client, me)
    response = await reserve(client, me, album, [{**file('x.webp'), 'preprocessing': {**hint(), **patch}}])
    assert response.status_code == 422
    async with db() as session:
        assert await session.scalar(select(Upload)) is None


async def upload_image(client, *, original=(300,400), actual=(30,40), kind='WEBP'):
    me, album = await setup(client); await consent(client, me)
    out=BytesIO(); Image.new('RGB', actual, 'blue').save(out, format=kind)
    data=out.getvalue()
    metadata={**hint(), 'original_width':original[0], 'original_height':original[1]}
    response=await reserve(client,me,album,[{**file('x.webp',len(data)), 'preprocessing':metadata}])
    assert response.status_code == 201, response.text
    entry=response.json()['data']['uploads'][0]
    assert (await client.put(entry['upload_url'],content=data,headers={**entry['required_headers'],**headers(me)})).status_code == 204
    path=f'/api/v1/albums/{album}/uploads/{entry["upload_id"]}'
    assert (await client.post(path+'/complete',json={},headers=headers(me))).status_code == 202
    return me,album,entry,path


@pytest.mark.asyncio
@pytest.mark.parametrize('original,actual,kind,ready,exact', [
    ((300,400),(30,40),'WEBP',True,True),
    ((301,400),(30,40),'WEBP',True,False),
    ((300,400),(31,40),'WEBP',False,None),
    ((30,40),(60,80),'WEBP',False,None),
    ((300,400),(30,40),'PNG',False,None),
])
async def test_decoded_dimensions_and_mime_authoritative(client,db,original,actual,kind,ready,exact):
    _,_,entry,path=await upload_image(client,original=original,actual=actual,kind=kind)
    assert await ValidationWorker(db,config()).run_once()
    assert (await client.get(path)).json()['data']['status'] == ('ready' if ready else 'rejected')
    async with db() as session:
        page=await session.get(Page,UUID(entry['page_id']))
        assert page.input_is_3_4 is exact
        if ready:
            assert page.captured_at_raw == hint()['captured_at_raw']
            assert page.captured_timezone == '+09:00'
            assert page.sort_date == '2020-01-02T03:04:05'


@pytest.mark.asyncio
async def test_legacy_media_snapshot_missing_quality_uses_frozen_default(client, db, monkeypatch):
    from backend.tests.integration.test_validation_worker import pending
    import backend.uploads.validation as validation
    _,_,entry,_,_=await pending(client)
    async with db() as session,session.begin():
        upload=await session.get(Upload,UUID(entry['upload_id']))
        saved=dict(upload.validation_config)
        saved['media']={k:v for k,v in saved['media'].items() if k not in {'NORMALIZED_WEBP_QUALITY','NORMALIZATION_VERSION'}}
        saved['media']['NORMALIZED_WEBP_LOSSLESS']=True
        upload.validation_config=saved
    real=validation.normalize_in_process
    seen=[]
    async def capture(*args,**kwargs):
        seen.append(kwargs['config'])
        return await real(*args,**kwargs)
    monkeypatch.setattr(validation,'normalize_in_process',capture)
    monkeypatch.setenv('NORMALIZED_WEBP_QUALITY','12')
    monkeypatch.setenv('NORMALIZATION_VERSION','2')
    assert await ValidationWorker(db,config()).run_once()
    assert seen[0]['NORMALIZED_WEBP_QUALITY']==90
    assert seen[0]['NORMALIZATION_VERSION']==1
    assert seen[0]['NORMALIZED_WEBP_LOSSLESS'] is True
    async with db() as session:
        assert (await session.get(Upload,UUID(entry['upload_id']))).validation_config==saved


@pytest.mark.asyncio
async def test_preprocessing_rejects_non_webp_reservation(client,db):
    me,album=await setup(client); await consent(client,me)
    response=await reserve(client,me,album,[{**file('x.png'),'preprocessing':hint()}])
    assert response.status_code==422


def test_exact_original_hint_cannot_make_square_pixels_passthrough(tmp_path):
    from backend.uploads.validation import preprocessing_hints
    from backend.media.contracts import MediaValidationError
    path=tmp_path/'tiny.webp';Image.new('RGB',(1,1)).save(path,'WEBP')
    with pytest.raises(MediaValidationError):
        preprocessing_hints({'preprocessing':{**hint(),'original_width':3,'original_height':4}},'image/webp',path)


@pytest.mark.asyncio
async def test_malformed_capture_date_preserves_raw_and_falls_back(client,db):
    me,album=await setup(client);await consent(client,me)
    out=BytesIO();Image.new('RGB',(30,40)).save(out,'WEBP');data=out.getvalue()
    response=await reserve(client,me,album,[{**file('x.webp',len(data)),
        'file_last_modified_at':'2024-01-02T00:00:00Z',
        'preprocessing':{**hint(),'captured_at_raw':'2024:99:99 99:99:99'}}])
    entry=response.json()['data']['uploads'][0]
    await client.put(entry['upload_url'],content=data,headers={**entry['required_headers'],**headers(me)})
    await client.post(f'/api/v1/albums/{album}/uploads/{entry["upload_id"]}/complete',json={},headers=headers(me))
    assert await ValidationWorker(db,config()).run_once()
    async with db() as session:
        page=await session.get(Page,UUID(entry['page_id']))
        assert page.captured_at_raw=='2024:99:99 99:99:99'
        assert page.sort_date=='2024-01-02T09:00:00' and page.sort_date_source=='file_modified'


@pytest.mark.asyncio
async def test_legacy_reservation_hash_replays_after_optional_field_added(client,db):
    from backend.models import IdempotencyRecord
    from backend.http.idempotency import request_hash
    me,album=await setup(client);await consent(client,me)
    files=[file('x.png')]
    response=await reserve(client,me,album,files)
    assert response.status_code==201
    old_body={'expected_version':1,'files':[{**files[0],'mime':None,'file_last_modified_at':None}]}
    async with db() as session,session.begin():
        record=await session.scalar(select(IdempotencyRecord).where(IdempotencyRecord.operation==f'POST /api/v1/albums/{album}/uploads'))
        record.request_hash=request_hash(old_body)
    replay=await reserve(client,me,album,files)
    assert replay.status_code==201 and replay.json()['data']==response.json()['data']
