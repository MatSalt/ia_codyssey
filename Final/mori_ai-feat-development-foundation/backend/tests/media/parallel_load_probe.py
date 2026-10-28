"""Actual codec overlap in a memory-limited container, synthetic media only."""
import asyncio
import json
from pathlib import Path
import tempfile
import time
from PIL import Image
from backend.media.process import normalize_in_process
from backend.media.contracts import MediaValidationError
from backend.media.fake_transform import optimize_in_process

async def main():
    started=time.monotonic()
    with tempfile.TemporaryDirectory(prefix='mori-parallel-load-') as directory:
        root=Path(directory)
        # Textured, high-detail input rather than a solid-color fixture.
        image=Image.effect_noise((8000,5000),32).convert('RGB')
        image.save(root/'large.jpg',quality=70);image.close()
        small=Image.effect_noise((3000,4000),32).point(lambda value: (value//4)*4).convert('RGBA')
        small.putalpha(180);small.save(root/'alpha.png');small.close()
        for path in root.iterdir():
            print(json.dumps({'fixture':path.name,'bytes':path.stat().st_size}),flush=True)
            assert path.stat().st_size<=20971520
        try:
            boundary=await normalize_in_process(root/'large.jpg','large.jpg')
            boundary_status='ok';del boundary
        except MediaValidationError as exc:
            boundary_status=exc.code
        print(json.dumps({'boundary_40mp':boundary_status}),flush=True)
        image=Image.effect_noise((3000,4000),32).convert('RGB')
        image.save(root/'regular.jpg',quality=70);image.close()
        result=await normalize_in_process(root/'regular.jpg','regular.jpg')
        # Discover normalized bytes from the public dataclass.
        (root/'result.webp').write_bytes(result.webp_bytes)
        del result
        # Six concurrent provider inputs at the maximum supported byte size.
        buffers=[b'x'*20971520 for _ in range(6)]
        completed=0
        for index in range(6):
            source=root/('regular.jpg' if index%2==0 else 'alpha.png')
            a,b=await asyncio.gather(normalize_in_process(source,source.name),optimize_in_process(root/'result.webp',{}))
            completed+=1;del a,b
            print(json.dumps({'pair':completed,'input':source.name}),flush=True)
        assert sum(map(len,buffers))==6*20971520
        cg=Path('/sys/fs/cgroup')
        peak=int((cg/'memory.peak').read_text())
        events=dict(line.split() for line in (cg/'memory.events').read_text().splitlines())
        summary={'boundary_40mp':boundary_status,'pairs':completed,'seconds':round(time.monotonic()-started,3),'container_peak_bytes':peak,'memory_events':events,'provider_buffer_bytes':sum(map(len,buffers))}
        print('PARALLEL_MEMORY '+json.dumps(summary),flush=True)
        assert int(events['oom_kill'])==0
        assert peak<1024**3*.8, '1 GiB deployment has less than 20% headroom'

if __name__=='__main__':asyncio.run(main())
