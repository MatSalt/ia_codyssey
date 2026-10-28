"""All-results completion in the caller's album/run/task settlement transaction."""
from datetime import datetime,timezone
from uuid import UUID
from sqlalchemy import select
from backend.models import Page,Task,MediaAsset


def ready_output(asset,album,page,role):
    return (asset is not None and asset.owner_id==album.owner_id and asset.album_id==album.id
        and asset.page_id==page.id and asset.role==role and asset.status=='ready' and asset.deleted_at is None
        and asset.mime=='image/webp' and asset.width is not None and asset.height is not None
        and asset.width>0 and asset.width*4==asset.height*3)


async def recompute_completion(session,album,run):
    if album.deleted_at is not None or album.status=='deleted' or run.status in {'cancelled','succeeded'} or not run.input_snapshot:
        return
    await session.flush()
    tasks=(await session.scalars(select(Task).where(Task.run_id==run.id).order_by(Task.id).with_for_update())).all()
    from backend.generation.resume_policy import classify_deferred_ai
    await classify_deferred_ai(session,album,run,tasks)
    for item in run.input_snapshot:
        page=await session.get(Page,UUID(item['page_id']))
        stages={t.stage:t for t in tasks if str(t.page_id)==item['page_id']}
        if (page is None or page.album_id!=album.id or page.removed_at is not None
            or set(stages)!={'caption','image_transform','optimize'} or any(t.status!='succeeded' for t in stages.values())
            or not isinstance(page.ai_caption,str) or not page.ai_caption.strip() or page.caption_text is None):return
        result=await session.get(MediaAsset,page.result_asset_id) if page.result_asset_id else None
        thumb=await session.get(MediaAsset,page.thumbnail_asset_id) if page.thumbnail_asset_id else None
        if not ready_output(result,album,page,'result') or not ready_output(thumb,album,page,'thumbnail'):return
    stamp=datetime.now(timezone.utc)
    run.status='succeeded';run.finished_at=stamp
    album.status='review_ready';album.updated_at=stamp;album.version+=1
