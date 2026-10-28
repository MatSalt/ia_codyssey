"""Subprocess harness: test-only fake AI with durable call counter and barriers."""
import asyncio
from datetime import datetime, timezone
from pathlib import Path
import os
import sys


class CountingAdapter:
    def __init__(self, root, block=True):
        self.root, self.block = root, block

    async def execute(self, attempt_id, stage):
        with (self.root/'calls').open('a') as f:
            f.write('call\n'); f.flush(); os.fsync(f.fileno())
        if self.block:
            (self.root/'barrier').touch()
        while self.block and not (self.root/'release').exists():
            await asyncio.sleep(.01)
        return {'caption': '보존된 한 문장.'}


async def main(phase, root):
    from backend.database import session_factory
    from backend.worker.runner import Runner, ResultStore
    from backend.generation.repository import claim_task
    db = session_factory()
    class BlockingStore(ResultStore):
        async def save(self, key, result):
            saved = await super().save(key, result)
            (root/'barrier').touch()
            while True:
                await asyncio.sleep(.01)
            return saved
    store = BlockingStore(root) if phase == 'saved' else ResultStore(root)
    runner = Runner(db, store, CountingAdapter(root, block=phase=='sent'))
    if phase == 'restart':
        await runner.maintenance()
        await runner.run_once()
        await db.kw['bind'].dispose()
    elif phase == 'prepared':
        async with db() as s:
            claim = await claim_task(s, datetime.now(timezone.utc), 90)
        await runner.prepare(claim)
        (root/'barrier').touch()
        while True:
            await asyncio.sleep(.01)
    else:
        await runner.run_once()


if __name__ == '__main__':
    asyncio.run(main(sys.argv[1], Path(sys.argv[2])))
