import hashlib
import pytest
from backend.generation.fake_adapter import FakeExecutor, FakeExecutionError
from backend.tests.storage.test_r2_adapter import storage, K

@pytest.mark.asyncio
async def test_duplicate_context_downloads_once_and_returns_verified_snapshot(storage):
    store,remote=storage
    store.write(K,b'original'); remote.calls.clear()
    sha=hashlib.sha256(b'original').hexdigest()
    context={'normalized_key':K,'normalized_sha':sha,'normalized_bytes':8,'key':K,'sha':sha,'bytes':8}
    result=await FakeExecutor(None,store)._verify(context)
    assert result=={K:b'original'}
    assert [op for op,_ in remote.calls]==['get']
    remote.objects['mori-ai/'+K]=b'modified'
    with pytest.raises(FakeExecutionError): await FakeExecutor(None,store)._verify(context)
    assert result[K]==b'original'

@pytest.mark.asyncio
async def test_conflicting_duplicate_metadata_rejected(storage):
    store,_=storage;store.write(K,b'original')
    sha=hashlib.sha256(b'original').hexdigest()
    context={'normalized_key':K,'normalized_sha':sha,'normalized_bytes':8,'key':K,'sha':sha,'bytes':9}
    with pytest.raises(FakeExecutionError): await FakeExecutor(None,store)._verify(context)


@pytest.mark.asyncio
async def test_cancel_during_private_input_write_waits_then_removes_file(monkeypatch):
    import asyncio,threading
    from pathlib import Path
    from backend.storage.snapshot import input_file
    started=threading.Event();release=threading.Event();paths=[]
    original=Path.write_bytes
    def slow_write(path,data):
        paths.append(path);started.set()
        assert release.wait(3)
        return original(path,data)
    monkeypatch.setattr(Path,'write_bytes',slow_write)
    async def use():
        async with input_file(b'verified'):raise AssertionError('cancelled before yield')
    work=asyncio.create_task(use())
    assert await asyncio.to_thread(started.wait,2)
    work.cancel()
    await asyncio.sleep(.01)
    assert not work.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):await work
    assert paths and not paths[0].exists() and not paths[0].parent.exists()
