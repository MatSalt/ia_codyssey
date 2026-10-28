"""Immutable original attempt envelopes, durable in private R2 storage."""
import asyncio
import hashlib
import json
from uuid import UUID

from backend.storage.r2 import StorageUnavailable


class R2ResultStore:
    def __init__(self, store):
        self.store = store

    @staticmethod
    def _key(key):
        if not isinstance(key, str) or str(UUID(key)) != key:
            raise ValueError('invalid attempt key')
        return key

    async def save(self, key, result):
        key = self._key(key)
        if not isinstance(result, dict):
            raise ValueError('invalid attempt result')
        payload = json.dumps(result, sort_keys=True, ensure_ascii=False)
        checksum = hashlib.sha256(payload.encode()).hexdigest()
        envelope = json.dumps({'key': key, 'payload': payload, 'sha256': checksum}).encode()
        await asyncio.to_thread(self.store.write_envelope, key, envelope)
        return checksum

    async def load(self, key, expected_checksum=None):
        def read():
            try:
                self._key(key)
                envelope = json.loads(self.store.read_envelope(key))
                if not isinstance(envelope, dict):
                    return None
                payload = envelope['payload']
                if not isinstance(payload, str):
                    return None
                checksum = hashlib.sha256(payload.encode()).hexdigest()
                if (envelope['key'] != key or envelope['sha256'] != checksum
                    or expected_checksum and checksum != expected_checksum):
                    return None
                result = json.loads(payload)
                return result if isinstance(result, dict) else None
            except StorageUnavailable:
                # A storage outage is not evidence that the original is absent.
                raise
            except (FileNotFoundError, ValueError, KeyError, TypeError):
                return None
        return await asyncio.to_thread(read)
