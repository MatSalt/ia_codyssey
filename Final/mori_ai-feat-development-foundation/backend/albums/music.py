"""One application-provided soundtrack; never serves user-uploaded media."""
from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

BGM_PATH = Path(__file__).resolve().parents[2] / 'assets' / 'audio' / 'bgm.mp3'
router = APIRouter()


def viewer_music():
    if not BGM_PATH.is_file():
        return None
    return {'track_id':'mori-bgm-v1','url':'/audio/bgm.mp3','title':'사진첩 배경음악'}


@router.api_route('/audio/bgm.mp3', methods=['GET','HEAD'], include_in_schema=False)
async def soundtrack():
    if not BGM_PATH.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(BGM_PATH, media_type='audio/mpeg', headers={'Cache-Control':'public, max-age=0, must-revalidate'})
