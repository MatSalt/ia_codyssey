"""Opt-in real R2 comparison using synthetic pixels, never existing user media.

Run inside the configured worker environment with --real-r2. Each mode gets
fresh scoped object names; all created remote objects are deleted in finally.
Output includes timings/hashes/bytes only. No AI API calls or database writes.
"""
import argparse
import asyncio
import hashlib
from io import BytesIO
import json
from pathlib import Path
import random
import tempfile
from time import perf_counter
from uuid import uuid4

from PIL import Image
import pillow_heif
from backend.settings import Settings
from backend.storage.r2 import R2Storage
from backend.storage.snapshot import input_file
from backend.media.process import normalize_in_process
from backend.uploads.service import config


async def measure(store, source, mode, media_config):
    keys={role:f'{uuid4()}/{uuid4()}/{uuid4()}/{role}' for role in ('source','normalized','thumbnail')}
    metrics={'mode':mode}
    try:
        store.write(keys['source'],source)
        expected=hashlib.sha256(source).hexdigest()
        start=perf_counter()
        read_start=start
        if mode=='legacy':
            assert store.stat(keys['source']).st_size==len(source)
            assert store.checksum(keys['source'])==expected
            path=store.path(keys['source'])
            metrics['input_seconds']=perf_counter()-read_start
            normal_start=perf_counter()
            normalized=await normalize_in_process(path,'source',config=media_config)
        else:
            data=store.read_bytes(keys['source'])
            assert len(data)==len(source) and hashlib.sha256(data).hexdigest()==expected
            metrics['input_seconds']=perf_counter()-read_start
            normal_start=perf_counter()
            async with input_file(data) as path:
                normalized=await normalize_in_process(path,'source',config=media_config)
        metrics['normalize_seconds']=perf_counter()-normal_start
        check_start=perf_counter()
        assert normalized.sha256==expected
        if mode=='legacy': assert store.checksum(keys['source'])==expected
        metrics['recheck_seconds']=perf_counter()-check_start
        persist_start=perf_counter()
        store.write(keys['normalized'],normalized.webp_bytes)
        store.write(keys['thumbnail'],normalized.thumbnail_bytes)
        metrics['persist_seconds']=perf_counter()-persist_start
        metrics['validation_seconds']=perf_counter()-start
        metrics['source_bytes']=len(source)
        metrics['normalized_bytes']=len(normalized.webp_bytes)
        expected_output=hashlib.sha256(normalized.webp_bytes).hexdigest()
        metrics['output_sha256']=expected_output
        ai_start=perf_counter()
        if mode=='legacy':
            for _ in range(2):
                assert store.checksum(keys['normalized'])==expected_output
                assert store.stat(keys['normalized']).st_size==len(normalized.webp_bytes)
            data=store.path(keys['normalized']).read_bytes()
        else:
            data=store.read_bytes(keys['normalized'])
        assert hashlib.sha256(data).hexdigest()==expected_output
        metrics['ai_input_seconds']=perf_counter()-ai_start
        metrics['source_gets']=3 if mode=='legacy' else 1
        metrics['ai_input_gets']=3 if mode=='legacy' else 1
        return metrics
    finally:
        for key in keys.values(): store.delete(key)


async def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--real-r2',action='store_true',required=True)
    parser.add_argument('--width',type=int,default=4032)
    parser.add_argument('--height',type=int,default=3024)
    args=parser.parse_args()
    if not (1<=args.width<=4096 and 1<=args.height<=4096): raise ValueError('bounded dimensions required')
    settings=Settings()
    if settings.storage_mode!='r2': raise ValueError('R2 configuration required')
    pillow_heif.register_heif_opener()
    # A reproducible high-detail grayscale fixture, intentionally not a private photo.
    pixels=bytes(96+x//4 for x in random.Random(20261016).randbytes(args.width*args.height))
    picture=Image.frombytes('L',(args.width,args.height),pixels).convert('RGB')
    with tempfile.TemporaryDirectory(prefix='mori-perf-cache-') as root:
        store=R2Storage(settings.model_copy(update={'storage_root':Path(root),
            'r2_key_prefix':settings.r2_key_prefix+'benchmark-'+str(uuid4())+'/'}))
        for index,kind in enumerate(('JPEG','PNG','HEIF')):
            out=BytesIO();picture.save(out,format=kind,quality=90)
            source=out.getvalue()
            order=('legacy','snapshot') if index%2==0 else ('snapshot','legacy')
            results=[]
            for mode in order:
                result=await measure(store,source,mode,config(settings));result['format']=kind
                results.append(result)
                print(json.dumps(result,sort_keys=True),flush=True)
            assert results[0]['output_sha256']==results[1]['output_sha256']
    print(json.dumps({'cleanup':'completed','ai_calls':0,'database_writes':0}),flush=True)


if __name__=='__main__':
    try: asyncio.run(main())
    except Exception as exc:
        print(json.dumps({'benchmark_error':type(exc).__name__}),flush=True)
        raise SystemExit(1) from None
