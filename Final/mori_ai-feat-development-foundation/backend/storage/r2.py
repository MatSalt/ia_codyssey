"""Private R2 objects. Remote state is authoritative; disk is a disposable cache."""
import hashlib
import os
from pathlib import Path
import re
import tempfile
from time import perf_counter
from backend.telemetry import emit, span
from types import SimpleNamespace

from backend.storage.local import KEY, MAX_BYTES, UUID_PART, LocalStorage

ENVELOPE_MAX_BYTES = 1024 * 1024
ATTEMPT = re.compile(rf'{UUID_PART}\Z')


class StorageUnavailable(OSError):
    """Sanitized remote storage failure, safe at application boundaries."""


class _ConditionalConflict(Exception):
    pass


def _safe_call(function, *args, **kwargs):
    # Raise outside the handler: even __context__ must not retain signed URLs/keys.
    failure = None
    started = perf_counter()
    operation = getattr(function, "__name__", "request")
    try:
        result = function(*args, **kwargs)
        if operation not in {"read", "close"}:
            metadata = result.get('ResponseMetadata', {}) if isinstance(result,dict) else {}
            emit("storage.request", operation=operation, outcome="succeeded", elapsed_ms=(perf_counter()-started)*1000,
                 retry_attempts=metadata.get('RetryAttempts') if isinstance(metadata,dict) else None)
        return result
    except Exception as error:
        response = getattr(error, 'response', None)
        response = response if isinstance(response, dict) else {}
        detail = response.get('Error')
        metadata = response.get('ResponseMetadata')
        code = detail.get('Code') if isinstance(detail, dict) else None
        status = metadata.get('HTTPStatusCode') if isinstance(metadata, dict) else None
        emit('storage.request', operation=operation, outcome='error', error_type=type(error).__name__,
             http_status=status, elapsed_ms=(perf_counter()-started)*1000)
        if code in ('NoSuchKey', 'NotFound', '404') or status == 404:
            failure = FileNotFoundError('remote object missing')
        elif code in ('PreconditionFailed', 'ConditionalRequestConflict', '412', '409') or status in (409, 412):
            failure = _ConditionalConflict('immutable object conflict')
        elif type(error).__name__ in ('ParamValidationError', 'UnknownParameterError'):
            failure = ValueError('invalid storage SDK parameters')
        else:
            failure = StorageUnavailable('remote storage unavailable')
    raise failure


class R2Storage:
    mode = 'r2'

    def __init__(self, settings, *, client=None):
        self._cache = LocalStorage(settings.storage_root)
        self.root = self._cache.root
        self._bucket = settings.r2_bucket_name
        self._prefix = settings.r2_key_prefix
        if client is None:
            client = self._make_client(settings)
        self._client = client

    @staticmethod
    def _make_client(settings):
        def create():
            import boto3
            from botocore.config import Config
            return boto3.client(
                's3', endpoint_url=settings.r2_endpoint_url,
                aws_access_key_id=settings.r2_access_key_id.get_secret_value(),
                aws_secret_access_key=settings.r2_secret_access_key.get_secret_value(),
                region_name=settings.r2_region,
                config=Config(signature_version='s3v4', retries={'mode': 'standard', 'total_max_attempts': 3},
                              connect_timeout=10, read_timeout=30,
                              request_checksum_calculation='when_required',
                              response_checksum_validation='when_required',
                              s3={'addressing_style': 'path'}),
            )
        return _safe_call(create)

    @staticmethod
    def _key(key):
        if not isinstance(key, str) or not KEY.fullmatch(key):
            raise ValueError('invalid storage key')
        return key

    @staticmethod
    def _envelope_key(attempt_id):
        if not isinstance(attempt_id, str) or not ATTEMPT.fullmatch(attempt_id):
            raise ValueError('invalid attempt id')
        return f'attempts/{attempt_id}.json'

    def _params(self, key):
        return {'Bucket': self._bucket, 'Key': self._prefix + key}

    def _read(self, key, limit):
        response = _safe_call(self._client.get_object, **self._params(key))
        body = response['Body']
        try:
            length = response.get('ContentLength')
            if length is not None and (not isinstance(length, int) or length < 0 or length > limit):
                raise ValueError('object too large')
            chunks = []
            total = 0
            while True:
                chunk = _safe_call(body.read, min(65536, limit + 1 - total))
                if not chunk:
                    break
                total += len(chunk)
                if total > limit:
                    raise ValueError('object too large')
                chunks.append(chunk)
            if length is not None and total != length:
                raise StorageUnavailable('incomplete remote object')
            return b''.join(chunks)
        finally:
            _safe_call(body.close)

    def _write(self, key, data, limit, mime):
        if not isinstance(data, bytes) or len(data) > limit:
            raise ValueError('invalid object size or bytes')
        conflict = False
        try:
            _safe_call(self._client.put_object, **self._params(key), Body=data,
                       ContentType=mime, ContentLength=len(data), IfNoneMatch='*')
        except _ConditionalConflict:
            conflict = True
        if conflict:
            if hashlib.sha256(self._read(key, limit)).digest() != hashlib.sha256(data).digest():
                raise ValueError('immutable object conflict')

    def read_bytes(self, key):
        """Fetch one bounded authoritative snapshot; never reuse a shared cache path."""
        with span("storage.download", storage_mode="r2") as timing:
            data = self._read(self._key(key), MAX_BYTES)
            timing["bytes"] = len(data)
            return data

    def path(self, key):
        key = self._key(key)
        path = self._cache.path(key, create=True)
        try:
            data = self._read(key, MAX_BYTES)
        except FileNotFoundError:
            path.unlink(missing_ok=True)
            raise
        fd, temporary = tempfile.mkstemp(prefix='.r2-', dir=path.parent)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return path

    def stat(self, key):
        key = self._key(key)
        try:
            response = _safe_call(self._client.head_object, **self._params(key))
        except FileNotFoundError:
            self._cache.delete(key)
            raise
        size = response.get('ContentLength')
        if type(size) is not int or not 0 <= size <= MAX_BYTES:
            raise ValueError('invalid remote object size')
        return SimpleNamespace(st_size=size)

    def checksum(self, key):
        return hashlib.sha256(self.path(key).read_bytes()).hexdigest()

    def exists(self, key):
        key = self._key(key)
        missing = False
        try:
            _safe_call(self._client.head_object, **self._params(key))
        except FileNotFoundError:
            missing = True
        if missing:
            self._cache.delete(key)
            return False
        return True

    def _delete(self, key):
        try:
            _safe_call(self._client.delete_object, **self._params(key))
        except FileNotFoundError:
            pass

    def delete(self, key):
        key = self._key(key)
        self._delete(key)
        self._cache.delete(key)

    def write(self, key, data):
        self._write(self._key(key), data, MAX_BYTES, 'image/webp')

    def write_envelope(self, attempt_id, data):
        self._write(self._envelope_key(attempt_id), data, ENVELOPE_MAX_BYTES, 'application/json')

    def read_envelope(self, attempt_id):
        return self._read(self._envelope_key(attempt_id), ENVELOPE_MAX_BYTES)

    def delete_envelope(self, attempt_id):
        self._delete(self._envelope_key(attempt_id))

    def _sign(self, key, ttl, operation, method, maximum, **extra):
        key = self._key(key)
        if type(ttl) is not int or not 1 <= ttl <= maximum:
            raise ValueError('invalid signing expiration')
        return _safe_call(self._client.generate_presigned_url, operation,
                          Params={**self._params(key), **extra}, ExpiresIn=ttl, HttpMethod=method)

    def sign_put(self, key, mime, declared, ttl):
        if type(declared) is not int or not 1 <= declared <= MAX_BYTES:
            raise ValueError('invalid declared size')
        if not isinstance(mime, str) or not mime or '\r' in mime or '\n' in mime:
            raise ValueError('invalid content type')
        return self._sign(key, ttl, 'put_object', 'PUT', 900,
                          ContentType=mime, ContentLength=declared, IfNoneMatch='*')

    def sign_get(self, key, ttl):
        return self._sign(key, ttl, 'get_object', 'GET', 300)

    def sign_head(self, key, ttl):
        return self._sign(key, ttl, 'head_object', 'HEAD', 300)
