"""Paid execution: verified originals, one reservation/dispatch, durable results only."""
import asyncio
import hashlib
from datetime import datetime, timezone
from io import BytesIO
from PIL import Image
from backend.models import Attempt
from backend.generation.fake_adapter import FakeExecutor, FakeExecutionError
from backend.generation.repository import _locked_task, _active
from backend.storage.factory import result_store
from backend.storage.r2 import StorageUnavailable
from backend.telemetry import span
from backend.generation.prompt_profiles import SUPPORTED_PROMPT_VERSIONS


class RealExecutionError(Exception):
    def __init__(self, code, *, safe_to_retry=False, dispatch_state='accepted_or_unknown'):
        super().__init__(code)
        self.code, self.safe_to_retry, self.dispatch_state = code, safe_to_retry, dispatch_state


class RealExecutor(FakeExecutor):
    # Runner must let this executor reserve funds before crossing dispatch boundary.
    manages_dispatch = True
    execution_mode = 'openai'

    def __init__(self, sessions, store, provider, ledger, settings):
        super().__init__(sessions, store)
        self.provider, self.ledger = provider, ledger
        self.caption_model, self.image_model = settings.openai_caption_model, settings.openai_image_model

    def accepts_config(self, config):
        return (config.get('execution_mode') == 'openai'
            and config.get('caption_provider') == 'openai' and config.get('image_provider') == 'openai'
            and config.get('caption_model') == self.caption_model and config.get('image_model') == self.image_model
            and config.get('prompt_version') in SUPPORTED_PROMPT_VERSIONS
            and config.get('pricing_profile') == 'openai-standard-2026-10-16-v1')

    async def _dispatch(self, context):
        async with self.sessions() as session, session.begin():
            rows = await _locked_task(session, context['task'])
            if (rows is None or not _active(*rows, context['fence'], datetime.now(timezone.utc))
                or not self.accepts_config(rows[1].config_snapshot)
                or rows[2].attempt_count != context['attempt_no']):
                return False
            # A sibling unknown may pause new AI after this task was prepared.
            # None distinguishes an unsent, explicitly resumable pause from stale work.
            if rows[1].status == 'action_required':
                return None
            attempt = await session.get(Attempt, context['attempt'])
            if attempt.dispatch_state != 'not_sent':
                return False
            attempt.status = 'dispatching'
            attempt.dispatch_state = 'accepted_or_unknown'
            return True

    async def execute(self, attempt_id, stage):
        if stage == 'optimize':
            return await super().execute(attempt_id, stage)
        from backend.generation.openai_provider import (ProviderFailure,
            CAPTION_RESERVATION_USD, IMAGE_RESERVATION_USD)
        from backend.generation.budget import BudgetExceeded
        if stage not in {'caption', 'image_transform'}:
            raise RealExecutionError('MEDIA_SAVE_FAILED', dispatch_state='not_sent')
        try:
            context = await self._context(attempt_id, stage)
            with span('generation.input', stage=stage):
                snapshots = await self._verify(context)
            # Submit exactly the authoritative snapshot verified in this attempt.
            source = snapshots[context['normalized_key']]
            if len(source) != context['normalized_bytes'] or hashlib.sha256(source).hexdigest() != context['normalized_sha']:
                raise FakeExecutionError('MEDIA_SAVE_FAILED')
            def validate_source():
                with Image.open(BytesIO(source)) as image:
                    if image.format != 'WEBP':
                        raise FakeExecutionError('MEDIA_SAVE_FAILED')
                    image.load()
            await asyncio.to_thread(validate_source)
        except (StorageUnavailable, OSError):
            raise RealExecutionError('MEDIA_SAVE_FAILED', safe_to_retry=True, dispatch_state='not_sent') from None
        amount = CAPTION_RESERVATION_USD if stage == 'caption' else IMAGE_RESERVATION_USD
        try:
            first = await self.ledger.reserve(attempt_id, amount)
        except BudgetExceeded:
            raise RealExecutionError('USAGE_LIMIT_EXCEEDED', safe_to_retry=True, dispatch_state='not_sent') from None
        if not first:
            # A previous process may have dispatched; duplicate reserve is never a send permit.
            raise RealExecutionError('AI_RESULT_UNKNOWN')
        dispatched = await self._dispatch(context)
        if not dispatched:
            await self.ledger.release_unsent(attempt_id)
            if dispatched is None:
                raise RealExecutionError('AI_TEMPORARY_FAILURE', safe_to_retry=True, dispatch_state='not_sent')
            raise RealExecutionError('MEDIA_SAVE_FAILED', dispatch_state='not_sent')
        try:
            with span('ai.provider', stage=stage):
                response = await (self.provider.caption(source, prompt_version=context['config']['prompt_version']) if stage == 'caption' else self.provider.transform(source))
        except ProviderFailure as exc:
            if exc.dispatch_state == 'not_sent':
                await self.ledger.release_unsent(attempt_id)
            else:
                await self.ledger.settle(attempt_id, getattr(exc, 'cost_usd', None),
                    getattr(exc, 'usage', {}) or {}, getattr(exc, 'request_id', None))
            raise
        try:
            if stage == 'caption':
                result = {'caption': response.caption}
            else:
                def validate_output():
                    try:
                        with Image.open(BytesIO(response.image)) as picture:
                            if picture.format != 'WEBP' or picture.size != (768,1024) or getattr(picture,'n_frames',1) != 1:
                                raise ValueError('invalid output')
                            picture.load()
                    except (OSError,ValueError,TypeError):
                        raise RealExecutionError('IMAGE_RATIO_INVALID', dispatch_state='responded') from None
                await asyncio.to_thread(validate_output)
                asset_id = await self._persist(context, 'transform_output', response.image)
                if asset_id is None:
                    raise RealExecutionError('MEDIA_SAVE_FAILED')
                result = {'asset_id': str(asset_id)}
            result['_accounting'] = {'cost_usd':str(response.cost_usd) if response.cost_usd is not None else None,
                'usage':response.usage, 'request_id':response.request_id}
            await result_store(self.store).save(str(attempt_id), result)
            return result
        except FakeExecutionError as exc:
            # Shared persistence errors after a paid response must never claim not_sent.
            raise RealExecutionError(exc.code, dispatch_state='accepted_or_unknown') from None

        finally:
            # Charge even rejected media, deletion, or a failed envelope write. A saved
            # envelope lets recovery replay usage if this DB transaction fails.
            await self.ledger.settle(attempt_id, response.cost_usd, response.usage, response.request_id)

    async def recover_accounting(self, attempt_id, result):
        from decimal import Decimal
        accounting = result.get('_accounting') if isinstance(result,dict) else None
        if accounting is not None:
            cost = accounting.get('cost_usd')
            await self.ledger.settle(attempt_id, Decimal(cost) if cost is not None else None,
                accounting.get('usage',{}), accounting.get('request_id'))
