"""DB execution and recovery with an explicitly injected AI port.

The default worker never invents AI/media success: it runs recovery and outbox
maintenance only until application adapters are installed. All file I/O is in
threads and outside database transactions; every heartbeat opens a new session.
"""
import asyncio
from contextlib import suppress
from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
from time import perf_counter
from pathlib import Path
from uuid import UUID, uuid4
from sqlalchemy import select, update, or_, func
from backend.models import Task, Attempt, Album, Run
from backend.telemetry import span, emit
from backend.generation.repository import claim_task, settle_task, _locked_task, _active, mark_action_required, result_fields, fail_invalid_result, reject_invalid_settlement
from backend.worker.jobs import enqueue_job, dispatch_outbox, recover_jobs


def utcnow():
    return datetime.now(timezone.utc)


class ResultStore:
    """Local durable attempt envelope; no user-provided filesystem paths."""
    def __init__(self, root: Path):
        self.root = root

    def _path(self, key):
        return self.root / 'attempts' / f'{UUID(key)}.json'

    async def save(self, key, result):
        def write():
            path = self._path(key)
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(result, sort_keys=True, ensure_ascii=False)
            checksum = hashlib.sha256(payload.encode()).hexdigest()
            envelope = json.dumps({'key': key, 'payload': payload, 'sha256': checksum})
            temporary = path.with_suffix(f'.{uuid4()}.tmp')
            try:
                with temporary.open('x') as f:
                    f.write(envelope); f.flush(); os.fsync(f.fileno())
                os.replace(temporary, path)
                fd = os.open(path.parent, os.O_DIRECTORY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
            finally:
                temporary.unlink(missing_ok=True)
            return checksum
        return await asyncio.to_thread(write)

    async def load(self, key, expected_checksum=None):
        def read():
            try:
                envelope = json.loads(self._path(key).read_text())
                checksum = hashlib.sha256(envelope['payload'].encode()).hexdigest()
                if envelope['key'] != key or envelope['sha256'] != checksum or (expected_checksum and checksum != expected_checksum):
                    return None
                result = json.loads(envelope['payload'])
                if not isinstance(result, dict):
                    return None
                return result
            except (OSError, ValueError, KeyError, TypeError):
                return None
        return await asyncio.to_thread(read)


class Runner:
    def __init__(self, sessions, store, adapter=None, *, lease_seconds=90, heartbeat_seconds=15, local_executor=None):
        if not 0 < heartbeat_seconds < lease_seconds:
            raise ValueError('heartbeat must be shorter than lease')
        self.sessions, self.store, self.adapter = sessions, store, adapter
        self.lease_seconds, self.heartbeat_seconds = lease_seconds, heartbeat_seconds
        self.local_executor = local_executor

    async def prepare(self, claim):
        async with self.sessions() as s, s.begin():
            rows = await _locked_task(s, claim.task_id)
            if rows is None or not _active(*rows, claim.fence_version, utcnow()):
                return None
            album, run, task, page = rows
            if task.requires_ai_call and run.status == 'action_required':
                task.status = 'queued'; task.lease_until = None
                from backend.generation.completion import recompute_completion
                await recompute_completion(s, album, run)
                return None
            handler=self.adapter if task.requires_ai_call else self.local_executor
            if hasattr(handler,'accepts_config') and not handler.accepts_config(run.config_snapshot):
                task.status='failed';task.lease_until=None;task.safe_to_retry=False
                task.error_code='AI_TEMPORARY_FAILURE'
                mark_action_required(album,run)
                return None
            used=await s.scalar(select(func.sum(Task.attempt_count)).where(Task.run_id==run.id)) or 0
            if used >= run.config_snapshot.get('attempt_budget',450):
                task.status='failed';task.lease_until=None;task.safe_to_retry=False
                task.error_code='AI_TEMPORARY_FAILURE' if task.requires_ai_call else 'MEDIA_SAVE_FAILED'
                mark_action_required(album,run)
                return None
            task.attempt_count += 1
            attempt = Attempt(task_id=task.id, attempt_no=task.attempt_count, fence_version=claim.fence_version)
            s.add(attempt); await s.flush()
            attempt.result_key = str(attempt.id)
            return attempt.id, task.stage, task.requires_ai_call

    async def _mark_sent(self, claim, attempt_id):
        async with self.sessions() as s, s.begin():
            rows = await _locked_task(s, claim.task_id)
            if rows is None or not _active(*rows, claim.fence_version, utcnow()):
                return False
            album, run, task, page = rows
            if task.requires_ai_call and run.status == 'action_required':
                task.status = 'queued'; task.lease_until = None
                from backend.generation.completion import recompute_completion
                await recompute_completion(s, album, run)
                return False
            attempt = await s.get(Attempt, attempt_id)
            attempt.status = 'dispatching'; attempt.dispatch_state = 'accepted_or_unknown'
            return True

    async def _heartbeat(self, claim):
        while True:
            await asyncio.sleep(self.heartbeat_seconds)
            async with self.sessions() as s, s.begin():
                now = utcnow()
                result = await s.execute(update(Task).where(Task.id == claim.task_id, Task.status == 'running', Task.fence_version == claim.fence_version, Task.lease_until > now).values(lease_until=now+timedelta(seconds=self.lease_seconds)))
                if not result.rowcount:
                    return

    async def _received(self, claim, attempt_id, result, checksum):
        async with self.sessions() as s, s.begin():
            rows = await _locked_task(s, claim.task_id)
            if rows is None:
                return False
            album, run, task, page = rows
            attempt = await s.get(Attempt, attempt_id)
            # Only owner/album/page-scoped IDs may reach cleanup or DB references.
            caption, asset_id, error = await result_fields(s, rows, result)
            # Preserve the original response even if scanner has marked it unknown.
            # Never let an older attempt replace the current attempt's result.
            if attempt.attempt_no != task.attempt_count:
                if asset_id:
                    await enqueue_job(s, 'cleanup_asset', asset_id)
                return False
            attempt.status = 'received'; attempt.result_sha256 = checksum; attempt.finished_at = utcnow()
            attempt.output_caption = caption
            attempt.output_asset_id = asset_id
            if album.deleted_at is not None or album.status == 'deleted' or page.removed_at is not None:
                if attempt.output_asset_id:
                    await enqueue_job(s, 'cleanup_asset', attempt.output_asset_id)
                return False
            if not _active(*rows, claim.fence_version, utcnow()):
                return False
            if error:
                fail_invalid_result(rows, attempt, error)
                return False
            task.output_caption = attempt.output_caption; task.output_asset_id = attempt.output_asset_id
            return True

    async def run_once(self, stage=None):
        if self.adapter is None and self.local_executor is None:
            return False
        started = perf_counter()
        async with self.sessions() as s:
            claim = await claim_task(s, utcnow(), self.lease_seconds, execution_mode=getattr(self.adapter,'execution_mode',None), stage=stage)
        if claim is None:
            return False
        emit('generation.claim', task_id=claim.task_id, stage=stage, elapsed_ms=(perf_counter()-started)*1000)
        with span('generation.task', task_id=claim.task_id, **({'stage': stage} if stage is not None else {})):
            return await self._execute_claim(claim)

    async def _execute_claim(self, claim):
        prepared = await self.prepare(claim)
        if prepared is None:
            return False
        attempt_id, stage, needs_ai = prepared
        executor = self.adapter if needs_ai else self.local_executor
        if executor is None:
            # No handler is not a successful job. Leave unsent attempt for scanner.
            return False
        heartbeat = asyncio.create_task(self._heartbeat(claim))
        work = None
        try:
            if needs_ai and not getattr(executor,'manages_dispatch',False) and not await self._mark_sent(claim, attempt_id):
                return False
            async def execute():
                with span('generation.execute', stage=stage, task_id=claim.task_id, attempt_id=attempt_id):
                    return await executor.execute(attempt_id, stage)
            work = asyncio.create_task(execute())
            done,_ = await asyncio.wait((work,heartbeat),return_when=asyncio.FIRST_COMPLETED)
            if heartbeat in done:
                work.cancel()
                with suppress(asyncio.CancelledError): await work
                if heartbeat.exception(): raise heartbeat.exception()
                return True
            result = await work
            with span('generation.persist', stage=stage, task_id=claim.task_id, attempt_id=attempt_id):
                checksum = await self.store.save(str(attempt_id), result)
            if await self._received(claim, attempt_id, result, checksum):
                async with self.sessions() as s:
                    if not await settle_task(s, claim.task_id, claim.fence_version, 'succeeded', utcnow()):
                        await reject_invalid_settlement(s, claim.task_id, claim.fence_version, utcnow())
            return True
        except asyncio.CancelledError:
            raise  # Shutdown preserves dispatch boundary; scanner determines safe recovery.
        except Exception as exc:
            # Explicit fake failures can prove no external request; generic AI failures cannot.
            from backend.generation.fake_adapter import FakeExecutionError
            from backend.generation.real_adapter import RealExecutionError
            # Import optional provider only for real mode; fake installations need no SDK.
            provider_failure = ()
            if getattr(executor,'manages_dispatch',False):
                from backend.generation.openai_provider import ProviderFailure
                provider_failure = (ProviderFailure,)
            definitive=isinstance(exc,(FakeExecutionError,RealExecutionError)+provider_failure)
            state=exc.dispatch_state if definitive else 'accepted_or_unknown'
            known_invalid=definitive and exc.code in {'CAPTION_INVALID','IMAGE_RATIO_INVALID','AI_REFUSED'}
            outcome='failed' if not needs_ai or definitive and (state in {'not_sent','rejected','responded'} or known_invalid) else 'unknown'
            async with self.sessions() as s,s.begin():
                rows=await _locked_task(s,claim.task_id)
                if rows is not None and _active(*rows,claim.fence_version,utcnow()):
                    task=rows[2]
                    task.error_code=exc.code if definitive else 'AI_RESULT_UNKNOWN' if needs_ai else 'MEDIA_SAVE_FAILED'
                    task.safe_to_retry=(exc.safe_to_retry and state in {'not_sent','rejected'}) if definitive else not needs_ai and task.has_persisted_input
                    attempt=await s.get(Attempt,attempt_id)
                    attempt.error_code=task.error_code
                    if definitive: attempt.dispatch_state=exc.dispatch_state
            # Without definitive not_sent/rejected evidence, never automatically retry AI.
            async with self.sessions() as s:
                await settle_task(s, claim.task_id, claim.fence_version, outcome, utcnow())
            return True
        finally:
            if work is not None and not work.done():
                work.cancel()
                with suppress(asyncio.CancelledError): await work
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat

    async def recover(self, now=None):
        now = now or utcnow()
        async with self.sessions() as s:
            task_ids = list(await s.scalars(select(Task.id).where(or_(Task.status == 'unknown', (Task.status == 'running') & (Task.lease_until <= now)))))
        recovered = 0
        for task_id in task_ids:
            async with self.sessions() as s:
                attempt = await s.scalar(select(Attempt).where(Attempt.task_id == task_id).order_by(Attempt.attempt_no.desc()).limit(1))
                key = attempt.result_key if attempt else None
                checksum = attempt.result_sha256 if attempt else None
                attempt_id = attempt.id if attempt else None
                recovery_stage = (await s.get(Task,task_id)).stage
                db_result = ({'caption': attempt.output_caption, 'asset_id': str(attempt.output_asset_id) if attempt.output_asset_id else None} if attempt and attempt.status == 'received' else None)
            # No row lock while looking for deterministic preserved output.
            result = await self.store.load(key, checksum) if key else None
            if result is None:
                result = db_result
            if result is None and attempt_id and hasattr(self.adapter,'recover_original'):
                result = await self.adapter.recover_original(attempt_id,recovery_stage)
                if result is not None:
                    await self.store.save(str(attempt_id),result)
            if result is not None and attempt_id and hasattr(self.adapter,'recover_accounting'):
                await self.adapter.recover_accounting(attempt_id,result)
            recovered_claim = None
            async with self.sessions() as s, s.begin():
                rows = await _locked_task(s, task_id)
                if rows is None:
                    continue
                album, run, task, page = rows
                if not (task.status == 'unknown' or (task.status == 'running' and task.lease_until and task.lease_until <= now)):
                    continue
                latest = await s.scalar(select(Attempt).where(Attempt.task_id == task_id).order_by(Attempt.attempt_no.desc()).limit(1))
                if (latest.id if latest else None) != attempt_id:
                    continue
                caption, asset_id, error = await result_fields(s, rows, result)
                if album.deleted_at is not None or album.status == 'deleted' or page.removed_at is not None or run.status == 'cancelled':
                    task.status = 'cancelled'; task.fence_version += 1; task.lease_until = None
                    if asset_id:
                        await enqueue_job(s, 'cleanup_asset', asset_id)
                    continue
                if result is not None:
                    latest.status = 'received'; latest.finished_at = now
                    latest.output_caption = caption
                    latest.output_asset_id = asset_id
                    if error:
                        fail_invalid_result(rows, latest, error)
                        continue
                    task.output_caption = latest.output_caption; task.output_asset_id = latest.output_asset_id
                    # Durable settlement only: this transient lease does not
                    # execute provider/media work or consume an execution lane.
                    task.fence_version += 1; task.status = 'running'; task.lease_until = now+timedelta(seconds=self.lease_seconds)
                    from backend.generation.repository import TaskClaim
                    recovered_claim = TaskClaim(task.id, task.fence_version, task.lease_until)
                elif latest is None or latest.dispatch_state in {'not_sent', 'rejected'}:
                    if task.status != 'unknown':
                        exhausted = task.attempt_count >= run.config_snapshot.get('max_attempts', 3)
                        task.status = 'failed' if exhausted else 'queued'
                        task.fence_version += 1; task.lease_until = None
                        if exhausted:
                            task.safe_to_retry = True
                            mark_action_required(album, run)
                else:
                    if task.status != 'unknown':
                        task.fence_version += 1
                    task.status = 'unknown'; task.lease_until = None
                    latest.status = 'unknown'; mark_action_required(album, run)
                    await enqueue_job(s, 'reconcile_attempt', latest.id)
            if recovered_claim:
                async with self.sessions() as s:
                    if await settle_task(s, task_id, recovered_claim.fence_version, 'succeeded', now):
                        recovered += 1
                    else:
                        await reject_invalid_settlement(s, task_id, recovered_claim.fence_version, now)
        return recovered

    async def maintenance(self):
        now = utcnow()
        await self.recover(now)
        async with self.sessions() as s:
            await recover_jobs(s, now)
        async with self.sessions() as s:
            await dispatch_outbox(s, now)
