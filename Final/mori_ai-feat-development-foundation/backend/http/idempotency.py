"""Canonical request identities and replay validation (no HTTP envelope persistence)."""
import hashlib
import json
from backend.http.errors import APIError


def request_hash(body):
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def require_key(value):
    if value is None or not value.strip() or len(value) > 512:
        raise APIError(422, 'VALIDATION_ERROR')
    return value


def replay(record, hashed):
    if record.request_hash != hashed:
        raise APIError(409, 'IDEMPOTENCY_CONFLICT', '같은 요청 키로 다른 내용을 보냈습니다.')
    return record.http_status, record.response_body
