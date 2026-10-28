import asyncio
import sys
from pathlib import Path
import pytest
from backend.media.process import normalize_in_process, _run_child
from backend.media.contracts import MediaValidationError


@pytest.mark.asyncio
async def test_timeout_does_not_block_heartbeat(tmp_path):
    marker=tmp_path/'pid'
    ticks=[]
    async def heartbeat():
        while True:
            ticks.append(1); await asyncio.sleep(.02)
    task=asyncio.create_task(heartbeat())
    try:
        with pytest.raises(MediaValidationError) as error:
            await _run_child([sys.executable,'-c',
                'import os,time,pathlib; pathlib.Path('+repr(str(marker))+').write_text(str(os.getpid())); time.sleep(30)'], .5)
        assert error.value.code=='IMAGE_PROCESS_TIMEOUT'
        assert len(ticks)>10
        import os
        with pytest.raises(ProcessLookupError): os.kill(int(marker.read_text()),0)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await task


@pytest.mark.asyncio
async def test_process_matches_normalize_and_cleans_temp(tmp_path,monkeypatch):
    from .test_normalize import source
    from backend.media.normalize import normalize
    import tempfile
    monkeypatch.setattr(tempfile,'tempdir',str(tmp_path))
    path=tmp_path/'source.png'; path.write_bytes(source())
    result=await normalize_in_process(path,'source.png',10)
    assert result==normalize(path.read_bytes(),'source.png')
    assert list(tmp_path.iterdir())==[path]


@pytest.mark.asyncio
async def test_process_propagates_validation(tmp_path):
    path=tmp_path/'bad'; path.write_bytes(b'bad')
    with pytest.raises(MediaValidationError) as error: await normalize_in_process(path,'x.png',10)
    assert error.value.code=='IMAGE_DECODE_FAILED'


@pytest.mark.asyncio
async def test_public_timeout_cleans_temp(tmp_path,monkeypatch):
    import tempfile
    from .test_normalize import source
    monkeypatch.setattr(tempfile,'tempdir',str(tmp_path))
    path=tmp_path/'source.png'; path.write_bytes(source())
    with pytest.raises(MediaValidationError) as error:
        await normalize_in_process(path,'x.png',0)
    assert error.value.code=='IMAGE_PROCESS_TIMEOUT'
    assert list(tmp_path.iterdir())==[path]


@pytest.mark.asyncio
async def test_memory_budget_terminates_child(monkeypatch,tmp_path):
    from backend.media import process
    monkeypatch.setattr(process,'CHILD_RSS_LIMIT',24*1024*1024)
    marker=tmp_path/'pid'
    with pytest.raises(MediaValidationError) as error:
        await _run_child([sys.executable,'-c','import os,time,pathlib; pathlib.Path('+repr(str(marker))+').write_text(str(os.getpid())); x=bytearray(40*1024*1024); time.sleep(30)'],5)
    assert error.value.code=='IMAGE_PROCESS_MEMORY_LIMIT'
    import os
    with pytest.raises(ProcessLookupError): os.kill(int(marker.read_text()),0)


@pytest.mark.asyncio
async def test_cancellation_reaps_child(tmp_path):
    marker=tmp_path/'pid'
    task=asyncio.create_task(_run_child([sys.executable,'-c','import os,time,pathlib; pathlib.Path('+repr(str(marker))+').write_text(str(os.getpid())); time.sleep(30)'],30))
    for _ in range(200):
        if marker.exists() and marker.read_text().isdigit(): break
        await asyncio.sleep(.01)
    assert marker.exists() and marker.read_text().isdigit()
    pid = int(marker.read_text())
    task.cancel()
    with pytest.raises(asyncio.CancelledError): await task
    import os
    with pytest.raises(ProcessLookupError): os.kill(pid,0)


@pytest.mark.asyncio
async def test_concurrent_normalizations_use_persisted_settings(tmp_path, monkeypatch):
    import os
    from io import BytesIO
    from PIL import Image
    output = BytesIO()
    Image.new('RGB', (300, 400), 'blue').save(output, format='PNG')
    source = tmp_path / 'source.png'
    source.write_bytes(output.getvalue())
    monkeypatch.setenv('NORMALIZED_MAX_EDGE', '4096')
    results = await asyncio.gather(
        normalize_in_process(source, 'source.png', 10, config={'NORMALIZED_MAX_EDGE': 120}),
        normalize_in_process(source, 'source.png', 10, config={'NORMALIZED_MAX_EDGE': 240}),
    )
    assert [(r.width, r.height) for r in results] == [(90, 120), (180, 240)]
    assert os.environ['NORMALIZED_MAX_EDGE'] == '4096'


@pytest.mark.asyncio
async def test_snapshot_cannot_override_arbitrary_child_environment(tmp_path):
    source = tmp_path / 'source.png'
    source.write_bytes(b'unused')
    with pytest.raises(MediaValidationError) as error:
        await normalize_in_process(source, 'source.png', config={'PYTHONPATH': '/other'})
    assert error.value.code == 'IMAGE_NORMALIZATION_FAILED'
