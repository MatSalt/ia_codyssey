"""Local fake canvas and result encoding in the existing bounded media child."""
import asyncio
from io import BytesIO
import json
from pathlib import Path
import sys
import tempfile
from PIL import Image
from backend.media.process import _run_child
from backend.media.contracts import MediaValidationError


def encode(image, *, quality=90, lossless=False):
    out=BytesIO()
    image.save(out,format='WEBP',quality=quality,lossless=lossless,exif=b'',icc_profile=b'',xmp=b'')
    return out.getvalue()


def opened(path):
    image=Image.open(path)
    if image.format!='WEBP' or image.width*image.height>40000000:
        raise ValueError('invalid WebP input')
    image.load()
    return image.convert('RGBA') if 'A' in image.getbands() else image.convert('RGB')


async def _process(path,mode,config,timeout_seconds=120):
    with tempfile.TemporaryDirectory(prefix='mori-fake-') as directory:
        await _run_child([sys.executable,'-m','backend.media.fake_transform',str(Path(path).resolve()),directory,mode,json.dumps(config)],timeout_seconds)
        root=Path(directory)
        metadata=json.loads((root/'metadata.json').read_text())
        # File reads stay off the worker loop as well as all Pillow work.
        result=await asyncio.to_thread((root/'result.webp').read_bytes)
        thumb=await asyncio.to_thread((root/'thumbnail.webp').read_bytes) if mode=='optimize' else None
        return result,thumb,metadata


async def fake_transform(normalized_path: Path, *, max_edge: int=4096) -> bytes:
    if type(max_edge) is not int or not 4<=max_edge<=4096:
        raise ValueError('invalid edge')
    result,_,_=await _process(normalized_path,'transform',{'max_edge':max_edge})
    return result


async def optimize_in_process(path: Path, config: dict):
    return await _process(path,'optimize',config)


def _main():
    source,directory,mode,raw=sys.argv[1:]
    config=json.loads(raw);root=Path(directory)
    image=opened(source)
    if mode=='transform':
        edge=config['max_edge']
        k=min(edge//4,max(1,(image.width+2)//3,(image.height+3)//4))
        canvas=Image.new('RGB',(3*k,4*k),'#ead8bb')
        contained=image.copy()
        contained.thumbnail(canvas.size,Image.Resampling.LANCZOS)
        at=((canvas.width-contained.width)//2,(canvas.height-contained.height)//2)
        canvas.paste(contained,at,contained.getchannel('A') if contained.mode=='RGBA' else None)
        result=encode(canvas,lossless=True);dimensions=canvas.size
    else:
        if image.width*4!=image.height*3:raise ValueError('result ratio invalid')
        edge=min(config.get('normalized_max_edge',4096),4096)
        if max(image.size)>edge:
            k=max(1,edge//4);image=image.resize((3*k,4*k),Image.Resampling.LANCZOS)
            result=encode(image,quality=config.get('result_webp_quality',90))
        else:
            # A verified, correctly sized WebP is reused without a second lossy encode.
            result=Path(source).read_bytes()
        dimensions=image.size
        edge=config.get('thumbnail_max_edge',480)
        k=max(1,min(image.width//3,image.height//4,edge//4))
        thumb=image.resize((3*k,4*k),Image.Resampling.LANCZOS)
        (root/'thumbnail.webp').write_bytes(encode(thumb,quality=config.get('thumbnail_webp_quality',80)))
    (root/'result.webp').write_bytes(result)
    (root/'metadata.json').write_text(json.dumps({'width':dimensions[0],'height':dimensions[1],
        'thumbnail_width':thumb.width if mode=='optimize' else None,'thumbnail_height':thumb.height if mode=='optimize' else None}))


if __name__=='__main__':_main()
