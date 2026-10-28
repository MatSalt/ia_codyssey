import pytest
from pydantic import ValidationError
from backend.settings import Settings

DB='postgresql+asyncpg://mori:local@postgres/mori_workflow_test'
def config(**extra):
    values=dict(database_url=DB,storage_mode='r2',r2_bucket_name='mori-test',
      r2_endpoint_url='https://'+'a'*32+'.r2.cloudflarestorage.com',
      r2_access_key_id='synthetic-access',r2_secret_access_key='synthetic-secret')
    values.update(extra)
    return Settings(**values)

def test_r2_requires_explicit_credentials_and_private_namespace():
    s=config()
    assert s.storage_mode=='r2' and s.r2_key_prefix=='mori-ai/'
    assert s.r2_region=='auto'
    assert 'synthetic-secret' not in repr(s) and 'synthetic-access' not in repr(s)
    assert s.r2_secret_access_key.get_secret_value()=='synthetic-secret'

@pytest.mark.parametrize('key',['r2_bucket_name','r2_endpoint_url','r2_access_key_id','r2_secret_access_key'])
def test_r2_missing_config_rejected(key):
    with pytest.raises(ValidationError):config(**{key:''})

@pytest.mark.parametrize('endpoint',['http://localhost:9000','https://foreign.invalid','https://'+'a'*32+'.r2.cloudflarestorage.com/bucket','https://user:password@'+'a'*32+'.r2.cloudflarestorage.com'])
def test_r2_endpoint_rejects_credentials_paths_and_foreign_hosts(endpoint):
    with pytest.raises(ValidationError):config(r2_endpoint_url=endpoint)

@pytest.mark.parametrize('prefix',['','../','a/../','/absolute/','a//b/','a?secret/'])
def test_r2_namespace_rejects_unsafe_prefix(prefix):
    with pytest.raises(ValidationError):config(r2_key_prefix=prefix)

def test_local_defaults_need_no_r2_credentials():
    assert Settings(database_url=DB).storage_mode=='local'

def test_local_storage_and_signer_compatible_methods(tmp_path):
    from backend.storage.local import LocalStorage
    from backend.storage.signing import Signer
    from uuid import uuid4
    key='/'.join(str(uuid4()) for _ in range(3))+'/source'
    store=LocalStorage(tmp_path)
    assert store.mode=='local' and not store.exists(key)
    store.write(key,b'fixture')
    assert store.exists(key)
    signer=Signer(tmp_path)
    url,headers=signer.upload_url(key,'/api/v1/private/uploads/test','test',9999999999,'image/png',7)
    assert headers=={'Content-Type':'image/png'}
    assert url==signer.url('PUT','/api/v1/private/uploads/test','test',9999999999,'image/png')
    assert signer.read_url(key,'/api/v1/private/read','test',9999999999,'image/png')==signer.url('GET','/api/v1/private/read','test',9999999999,'image/png')
