"""V09: 50 sequential 40MP synthetic inputs under a 1GiB container."""
import asyncio
import json
from pathlib import Path
import resource
import tempfile
import time
from PIL import Image
from backend.media.process import normalize_in_process
from backend.media.contracts import MediaValidationError


async def main():
    started=time.monotonic(); results=[]
    with tempfile.TemporaryDirectory(prefix='mori-load-') as directory:
        root=Path(directory)
        # Sequential processing retains source files, never decoded batches.
        image=Image.new('RGB',(8000,5000),(24,86,132))
        image.save(root/'template.png'); image.close()
        raw=(root/'template.png').read_bytes()
        for index in range(50): (root/f'{index}.png').write_bytes(raw)
        del raw
        for index in range(50):
            tick=time.monotonic()
            try:
                result=await normalize_in_process(root/f'{index}.png','synthetic.png',120)
                status='ok'; del result
            except MediaValidationError as error: status=error.code
            entry={'index':index,'status':status,'seconds':round(time.monotonic()-tick,3)}
            results.append(entry); print(json.dumps(entry),flush=True)
    peak_kib=resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    summary={'count':50,'success':sum(x['status']=='ok' for x in results),
             'child_peak_rss_kib':peak_kib,'worker_peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
             'seconds':round(time.monotonic()-started,3),'child_budget_mib':512,'worker_limit_mib':1024}
    cgroup=Path('/sys/fs/cgroup')
    if (cgroup/'memory.peak').exists():
        summary['container_memory_peak_bytes']=int((cgroup/'memory.peak').read_text())
        summary['container_memory_events']=(cgroup/'memory.events').read_text().strip().splitlines()
    print(json.dumps(summary),flush=True)
    if summary['success']!=50 or peak_kib>512*1024 or summary.get('container_memory_peak_bytes',0)>1024*1024*1024*.8: raise SystemExit(1)

if __name__=='__main__': asyncio.run(main())
