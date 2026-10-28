"""Structured timings only: no exception bodies, URLs, object keys or user text."""
import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import json
import logging
import math
import re
from time import perf_counter
from uuid import UUID

_LOG = logging.getLogger('mori.performance')
_CONTEXT = ContextVar('mori_performance_context', default={})
_NUMERIC = {'elapsed_ms','queue_age_ms','bytes','http_status','attempt_no','retry_attempts'}
_LABELS = {'stage','operation','outcome','error_type','error_code','kind','storage_mode'}
_IDS = {'task_id','attempt_id','job_id','run_id','request_id'}


def emit(event, **fields):
    record = {'event': event, 'timestamp': datetime.now(timezone.utc).isoformat()}
    for key,value in {**_CONTEXT.get(), **fields}.items():
        if key in _NUMERIC and type(value) in (int,float) and math.isfinite(value):
            record[key] = round(value,3)
        elif key in _LABELS and isinstance(value,str) and re.fullmatch(r'[A-Za-z0-9_.-]{1,80}',value):
            record[key] = value
        elif key in _IDS:
            try: record[key] = str(UUID(str(value)))
            except (ValueError,TypeError,AttributeError): pass
    _LOG.info(json.dumps(record,sort_keys=True))


@contextmanager
def span(event, **fields):
    started = perf_counter()
    token = _CONTEXT.set({**_CONTEXT.get(), **fields})
    result = {}
    try:
        yield result
    except BaseException as exc:
        result.update(outcome='cancelled' if isinstance(exc,asyncio.CancelledError) else 'error',
                      error_type=type(exc).__name__)
        code = getattr(exc,'code',None)
        if isinstance(code,str): result['error_code'] = code
        raise
    else:
        result.setdefault('outcome','succeeded')
    finally:
        emit(event, **{**result, 'elapsed_ms': (perf_counter()-started)*1000})
        _CONTEXT.reset(token)


def configure_web_logging():
    """Enable only the sanitized performance logger, not SDK/access logs."""
    if not _LOG.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter('%(levelname)s %(message)s'))
        _LOG.addHandler(handler)
    _LOG.setLevel(logging.INFO)
    _LOG.propagate = True
