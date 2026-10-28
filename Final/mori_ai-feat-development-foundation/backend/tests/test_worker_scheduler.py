import asyncio
from collections import Counter
import pytest


@pytest.mark.asyncio
async def test_lanes_overlap_are_bounded_and_stop_drains():
    from backend.worker.scheduler import run_worker
    stopped = asyncio.Event()
    active = Counter()
    peaks = Counter()
    entered = asyncio.Event()
    class Validation:
        async def run_once(self):
            active['validation'] += 1
            peaks['validation'] = max(peaks['validation'], active['validation'])
            try:
                await asyncio.sleep(0)
            finally:
                active['validation'] -= 1
        async def scan_incomplete_uploads(self, now, **kwargs):
            return None
    class Runner:
        async def run_once(self, stage=None):
            active[stage] += 1
            peaks[stage] = max(peaks[stage], active[stage])
            if sum(active[s] for s in ('caption', 'image_transform', 'optimize')) == 7:
                entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                active[stage] -= 1
        async def maintenance(self):
            peaks['maintenance'] += 1
    work = asyncio.create_task(run_worker(Validation(), Runner(), stopped, poll_seconds=.001))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        await asyncio.sleep(.02)
        assert peaks['validation'] == 1
        assert peaks['maintenance'] > 1
        assert peaks['caption'] == 4
        assert peaks['image_transform'] == 2
        assert peaks['optimize'] == 1
    finally:
        stopped.set()
        await asyncio.wait_for(work, 1)
    assert sum(active.values()) == 0


@pytest.mark.asyncio
async def test_idle_loops_do_not_accumulate_tasks_and_failure_recovers():
    from backend.worker.scheduler import run_worker
    stopped = asyncio.Event()
    calls = 0
    class Validation:
        async def run_once(self):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError('private text must not be logged')
        async def scan_incomplete_uploads(self, now, **kwargs): pass
    class Runner:
        async def maintenance(self): pass
    baseline = len(asyncio.all_tasks())
    work = asyncio.create_task(run_worker(Validation(), Runner(), stopped, poll_seconds=.001, generation_enabled=False))
    await asyncio.sleep(.02)
    count = len(asyncio.all_tasks())
    await asyncio.sleep(.04)
    assert len(asyncio.all_tasks()) <= count + 1
    assert calls > 2
    stopped.set()
    await work
    assert len(asyncio.all_tasks()) == baseline


@pytest.mark.asyncio
async def test_parent_cancellation_drains_maintenance_and_storage():
    from backend.worker.scheduler import run_worker
    active = set()
    all_entered = asyncio.Event()
    async def block(name):
        active.add(name)
        if len(active) == 4: all_entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            active.remove(name)
    class Validation:
        async def run_once(self): await block('validation')
        async def scan_incomplete_uploads(self, now, **kwargs): await block('storage')
    class Runner:
        async def maintenance(self): await block('maintenance')
    async def oauth(): await block('oauth')
    work = asyncio.create_task(run_worker(Validation(), Runner(), asyncio.Event(),
        poll_seconds=.01, generation_enabled=False, oauth_cleanup=oauth))
    await asyncio.wait_for(all_entered.wait(), 1)
    work.cancel()
    with pytest.raises(asyncio.CancelledError): await work
    assert not active
