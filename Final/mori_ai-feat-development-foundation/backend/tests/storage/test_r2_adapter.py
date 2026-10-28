import hashlib
import io
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

K = '11111111-1111-1111-1111-111111111111/' * 3 + 'normalized'
A = '22222222-2222-2222-2222-222222222222'

class RemoteError(Exception):
    def __init__(self, status, code=None):
        super().__init__('SECRET https://private.example/signed')
        self.response = {'Error': {'Code': code or str(status)}, 'ResponseMetadata': {'HTTPStatusCode': status}}

class FakeS3:
    def __init__(self):
        self.objects = {}
        self.calls = []
        self.streams = []
        self.error = None
        self.lock = threading.Lock()
    def _call(self, op, kw):
        self.calls.append((op, kw))
        if self.error: raise self.error
        assert kw['Bucket'] == 'new-bucket'
    def put_object(self, **kw):
        self._call('put', kw)
        assert kw['IfNoneMatch'] == '*'
        with self.lock:
            if kw['Key'] in self.objects: raise RemoteError(412)
            self.objects[kw['Key']] = kw['Body']
        return {}
    def get_object(self, **kw):
        self._call('get', kw)
        if kw['Key'] not in self.objects: raise RemoteError(404, 'NoSuchKey')
        body = io.BytesIO(self.objects[kw['Key']]); self.streams.append(body)
        return {'Body': body, 'ContentLength': len(self.objects[kw['Key']])}
    def head_object(self, **kw):
        self._call('head', kw)
        if kw['Key'] not in self.objects: raise RemoteError(404)
        return {'ContentLength': len(self.objects[kw['Key']])}
    def delete_object(self, **kw):
        self._call('delete', kw); self.objects.pop(kw['Key'], None); return {}
    def generate_presigned_url(self, operation, **kw):
        self.calls.append((operation, kw)); return 'https://fixed.example/signed'

@pytest.fixture
def storage(tmp_path):
    from backend.storage.r2 import R2Storage
    settings = SimpleNamespace(storage_root=tmp_path, r2_bucket_name='new-bucket', r2_key_prefix='mori-ai/')
    client = FakeS3()
    return R2Storage(settings, client=client), client

def test_remote_authority_cache_refresh_and_missing_cleanup(storage):
    s, c = storage
    s.write(K, b'first')
    p = s.path(K); assert p.read_bytes() == b'first'
    p.write_bytes(b'stale')
    assert s.checksum(K) == hashlib.sha256(b'first').hexdigest()
    assert s.stat(K).st_size == 5
    del c.objects['mori-ai/' + K]
    with pytest.raises(FileNotFoundError): s.path(K)
    assert not p.exists()
    assert all(x.closed for x in c.streams)

def test_immutable_remote_write_conflict_and_same_bytes(storage):
    s, c = storage
    s.write(K, b'a'); s.write(K, b'a')
    with pytest.raises(ValueError): s.write(K, b'b')
    assert c.objects['mori-ai/' + K] == b'a'
    assert c.calls[0][1]['ContentType'] == 'image/webp'

def test_exists_delete_are_remote_and_idempotent(storage):
    s, c = storage
    assert not s.exists(K)
    s.write(K, b'a'); assert s.exists(K)
    p = s.path(K); s.delete(K); s.delete(K)
    assert not s.exists(K) and not p.exists()

@pytest.mark.parametrize('key', ['../x', 'attempts/' + A + '.json', K.upper(), K + '/x', '/'+K, K.replace('normalized', 'other')])
def test_namespace_rejected_without_remote_access(storage, key):
    s, c = storage
    for call in (s.path, s.exists, s.delete, lambda k: s.write(k,b'a'), lambda k: s.sign_get(k,60)):
        with pytest.raises(ValueError): call(key)
    assert not c.calls

def test_bounds_close_stream_and_never_cache_oversized(storage):
    s, c = storage
    with pytest.raises(ValueError): s.write(K, b'x' * (20*1024*1024+1))
    c.objects['mori-ai/'+K] = b'x' * (20*1024*1024+1)
    with pytest.raises(ValueError): s.path(K)
    assert c.streams[-1].closed
    assert not (s.root/K).exists()
    with pytest.raises(ValueError): s.write_envelope(A, b'x'*(1024*1024+1))

def test_envelope_remote_immutable_isolated_namespace(storage):
    s, c = storage
    s.write_envelope(A,b'{}'); s.write_envelope(A,b'{}')
    assert s.read_envelope(A) == b'{}'
    assert c.objects['mori-ai/attempts/'+A+'.json'] == b'{}'
    with pytest.raises(ValueError): s.write_envelope(A,b'{"changed":1}')
    with pytest.raises(ValueError): s.read_envelope('../'+A)
    s.delete_envelope(A); s.delete_envelope(A)
    with pytest.raises(FileNotFoundError): s.read_envelope(A)

@pytest.mark.parametrize('error', [RemoteError(503), OSError('SECRET https://private.example'), RemoteError(403)])
def test_remote_errors_are_sanitized_without_exception_context(storage,error):
    from backend.storage.r2 import StorageUnavailable
    s,c=storage; c.error=error
    with pytest.raises(StorageUnavailable) as caught: s.exists(K)
    assert 'SECRET' not in str(caught.value)
    assert caught.value.__context__ is None and caught.value.__cause__ is None

def test_signing_params_and_expiry_limits(storage):
    s,c=storage
    assert s.sign_put(K,'image/heic',123,900).startswith('https://fixed.example')
    op,kw=c.calls[-1]
    assert op=='put_object'
    assert kw=={'Params':{'Bucket':'new-bucket','Key':'mori-ai/'+K,'ContentType':'image/heic','ContentLength':123,'IfNoneMatch':'*'},'ExpiresIn':900,'HttpMethod':'PUT'}
    s.sign_get(K,300); assert c.calls[-1][0]=='get_object'
    s.sign_head(K,1); assert c.calls[-1][0]=='head_object'
    for ttl in (0,901,True):
        with pytest.raises(ValueError): s.sign_put(K,'image/webp',1,ttl)
    for ttl in (0,301):
        with pytest.raises(ValueError): s.sign_get(K,ttl)
    for size in (0,20*1024*1024+1,True):
        with pytest.raises(ValueError): s.sign_put(K,'image/webp',size,10)

def test_concurrent_conflicting_writers_never_overwrite(storage):
    s,c=storage
    def write(data):
        try: s.write(K,data); return True
        except ValueError: return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes=list(pool.map(write,[b'a',b'b']))
    assert sorted(outcomes)==[False,True]
    assert c.objects['mori-ai/'+K] in (b'a',b'b')

@pytest.mark.parametrize('length,data,error', [(None,b'x'*(20*1024*1024+1),ValueError),(8,b'short',OSError)])
def test_stream_bounds_apply_without_trusting_metadata(storage,length,data,error):
    s,c=storage
    body=io.BytesIO(data)
    c.get_object=lambda **kw: {'Body':body,'ContentLength':length}
    with pytest.raises(error): s.path(K)
    assert body.closed and not (s.root/K).exists()


def test_network_failure_during_stream_closes_and_sanitizes(storage):
    from backend.storage.r2 import StorageUnavailable
    s,c=storage
    class Broken(io.BytesIO):
        def read(self,n): raise OSError('SECRET https://signed.example')
    body=Broken()
    c.get_object=lambda **kw: {'Body':body}
    with pytest.raises(StorageUnavailable) as caught: s.path(K)
    assert body.closed and caught.value.__context__ is None


def test_conditional_409_compares_remote_and_never_uses_cache(storage):
    s,c=storage
    c.objects['mori-ai/'+K]=b'remote'
    s.path(K).write_bytes(b'local')
    def conflict(**kw): raise RemoteError(409)
    c.put_object=conflict
    s.write(K,b'remote')
    with pytest.raises(ValueError): s.write(K,b'local')


def test_sdk_parameter_errors_remain_value_errors_without_secret(storage):
    s,c=storage
    ParamValidationError=type('ParamValidationError',(Exception,),{})
    c.error=ParamValidationError('SECRET URL')
    with pytest.raises(ValueError) as caught: s.exists(K)
    assert caught.value.__context__ is None and 'SECRET' not in str(caught.value)


def test_cache_symlink_cannot_escape(storage,tmp_path):
    s,c=storage
    outside=tmp_path/'outside'; outside.mkdir()
    (s.root/K.split('/')[0]).symlink_to(outside,target_is_directory=True)
    c.objects['mori-ai/'+K]=b'data'
    with pytest.raises(ValueError): s.path(K)
    assert not list(outside.iterdir())


def test_envelope_read_is_bounded_and_stream_closed(storage):
    s,c=storage
    c.objects['mori-ai/attempts/'+A+'.json']=b'x'*(1024*1024+1)
    with pytest.raises(ValueError): s.read_envelope(A)
    assert c.streams[-1].closed


def test_sdk_client_explicit_credentials_and_bounded_configuration(tmp_path,monkeypatch):
    import sys
    from backend.storage.r2 import R2Storage
    observed={}
    class Secret:
        def __init__(self,value): self.value=value
        def get_secret_value(self): return self.value
    class Config:
        def __init__(self,**kw): observed['config']=kw
    def client(service,**kw):
        observed['service']=service; observed['client']=kw
        return FakeS3()
    monkeypatch.setitem(sys.modules,'boto3',SimpleNamespace(client=client))
    monkeypatch.setitem(sys.modules,'botocore.config',SimpleNamespace(Config=Config))
    settings=SimpleNamespace(storage_root=tmp_path,r2_bucket_name='new-bucket',r2_key_prefix='mori-ai/',
        r2_endpoint_url='https://fixed.example',r2_access_key_id=Secret('explicit-id'),
        r2_secret_access_key=Secret('explicit-secret'),r2_region='auto')
    s=R2Storage(settings)
    assert s.mode=='r2'
    assert observed['service']=='s3'
    assert observed['client']['aws_access_key_id']=='explicit-id'
    assert observed['client']['aws_secret_access_key']=='explicit-secret'
    assert observed['client']['endpoint_url']=='https://fixed.example'
    assert observed['config']=={'signature_version':'s3v4','retries':{'mode':'standard','total_max_attempts':3},
        'connect_timeout':10,'read_timeout':30,'request_checksum_calculation':'when_required',
        'response_checksum_validation':'when_required','s3':{'addressing_style':'path'}}


def test_read_bytes_fetches_authority_once_without_shared_cache(storage):
    s,c=storage
    s.write(K,b'original')
    c.calls.clear()
    assert s.read_bytes(K)==b'original'
    assert [op for op,_ in c.calls]==['get']
    c.objects['mori-ai/'+K]=b'changed'
    assert s.read_bytes(K)==b'changed'
    assert not (s.root/K).exists()


def test_storage_telemetry_keeps_status_but_redacts_sdk_message(storage,caplog):
    import json,logging
    s,c=storage; c.error=RemoteError(503,'ServiceUnavailable')
    caplog.set_level(logging.INFO,logger='mori.performance')
    with pytest.raises(OSError): s.exists(K)
    events=[json.loads(r.message) for r in caplog.records if r.name=='mori.performance']
    assert events[-1]['http_status']==503
    assert events[-1]['error_type']=='RemoteError'
    assert events[-1]['operation']=='head_object'
    assert 'SECRET' not in caplog.text and K not in caplog.text


def test_sdk_error_with_none_response_is_sanitized(storage,caplog):
    import logging
    from backend.storage.r2 import StorageUnavailable
    class ConnectionClosedError(Exception):
        response=None
    s,c=storage;c.error=ConnectionClosedError('SECRET https://signed.example')
    caplog.set_level(logging.INFO,logger='mori.performance')
    with pytest.raises(StorageUnavailable) as caught:s.exists(K)
    assert caught.value.__context__ is None and caught.value.__cause__ is None
    assert 'SECRET' not in caplog.text


def test_sdk_retries_connection_close_bounded_without_exposing_endpoint(monkeypatch,tmp_path,caplog):
    import logging
    from botocore.exceptions import ConnectionClosedError
    from botocore.awsrequest import AWSResponse
    from botocore.httpsession import URLLib3Session
    from pydantic import SecretStr
    from backend.storage.r2 import R2Storage,StorageUnavailable
    attempts=[]
    success=True
    class Raw:
        def stream(self,*args,**kwargs):return iter(())
    def send(self,request):
        attempts.append(1)
        if len(attempts)%3 or not success:
            raise ConnectionClosedError(endpoint_url='https://SECRET.example')
        return AWSResponse(request.url,200,{'content-length':'3'},Raw())
    monkeypatch.setattr(URLLib3Session,'send',send)
    monkeypatch.setattr('botocore.endpoint.time.sleep',lambda _:None)
    settings=SimpleNamespace(storage_root=tmp_path,r2_bucket_name='test',r2_key_prefix='qa/',
        r2_endpoint_url='https://SECRET.example',r2_region='auto',
        r2_access_key_id=SecretStr('key'),r2_secret_access_key=SecretStr('secret'))
    caplog.set_level(logging.INFO,logger='mori.performance')
    store=R2Storage(settings)
    assert store.stat(K).st_size==3 and len(attempts)==3
    attempts.clear();success=False
    with pytest.raises(StorageUnavailable) as caught:store.stat(K)
    assert len(attempts)==3
    assert caught.value.__context__ is None
    assert 'SECRET' not in caplog.text
