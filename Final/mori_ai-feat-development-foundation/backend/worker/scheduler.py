"""Fixed, owned polling lanes: no task is allocated per queued or idle item."""
import asyncio
import logging
from datetime import datetime, timezone
from functools import partial

STAGE_LIMITS = {'caption': 4, 'image_transform': 2, 'optimize': 1}


async def _poll(operation, stopped, interval, name):
    while not stopped.is_set():
        try:
            await operation()
        except Exception as exc:
            # Exceptions can carry provider payloads or signed URLs.
            logging.warning('Worker %s failed error_class=%s', name, type(exc).__name__)
        try:
            await asyncio.wait_for(stopped.wait(), timeout=interval)
        except TimeoutError:
            pass


async def run_worker(validation, runner, stopped, *, poll_seconds,
                     generation_enabled=True, oauth_cleanup=None, goods_operation=None):
    if poll_seconds <= 0:
        raise ValueError('poll_seconds must be positive')
    async def scan():
        await validation.scan_incomplete_uploads(datetime.now(timezone.utc), limit=10)
    operations = [(_poll(validation.run_once, stopped, poll_seconds, 'validation')),
                  (_poll(runner.maintenance, stopped, poll_seconds, 'maintenance')),
                  (_poll(scan, stopped, 30, 'storage_scan'))]
    if oauth_cleanup is not None:
        operations.append(_poll(oauth_cleanup, stopped, 60, 'oauth_cleanup'))
    if goods_operation is not None:
        operations.append(_poll(goods_operation, stopped, poll_seconds, 'goods'))
    if generation_enabled:
        for stage, count in STAGE_LIMITS.items():
            for _ in range(count):
                operations.append(_poll(partial(runner.run_once, stage=stage), stopped, poll_seconds, stage))
    owned = [asyncio.create_task(op) for op in operations]
    try:
        await stopped.wait()
    finally:
        for task in owned:
            task.cancel()
        await asyncio.gather(*owned, return_exceptions=True)
