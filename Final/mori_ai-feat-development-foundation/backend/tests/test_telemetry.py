import json
import logging
import pytest


def test_span_records_duration_and_safe_metadata_without_error_body(caplog):
    from backend.telemetry import span
    caplog.set_level(logging.INFO, logger='mori.performance')
    with pytest.raises(OSError):
        with span('storage.request', operation='get_object', task_id='11111111-1111-1111-1111-111111111111', url='https://SECRET', key='SECRET', caption='SECRET'):
            raise OSError('SECRET signed URL token')
    event=json.loads(caplog.records[-1].message)
    assert event['event']=='storage.request' and event['elapsed_ms']>=0
    assert event['outcome']=='error' and event['error_type']=='OSError'
    assert 'SECRET' not in caplog.text


def test_cancellation_is_recorded_and_propagated(caplog):
    import asyncio
    from backend.telemetry import span
    caplog.set_level(logging.INFO, logger='mori.performance')
    with pytest.raises(asyncio.CancelledError):
        with span('generation.execute', stage='caption'):
            raise asyncio.CancelledError()
    assert json.loads(caplog.records[-1].message)['outcome']=='cancelled'
