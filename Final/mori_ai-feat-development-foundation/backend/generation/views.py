"""Public v1.3 GenerationView. No provider, storage or prompt details escape."""
from sqlalchemy import select
from backend.albums import repository as albums
from backend.http.errors import APIError
from backend.models import Run, Task, Page
from backend.generation.service import eligible_for_run

STAGES = ('caption','image_transform','optimize')


async def generation_view(session, owner_id, album_id, run_id=None):
    album=await albums.find_album(session,owner_id,album_id,lock=True)
    if album is None:
        raise APIError(404,'RESOURCE_NOT_FOUND')
    query=select(Run).where(Run.album_id == album_id)
    if run_id is not None:
        query=query.where(Run.id == run_id)
    run=await session.scalar(query.order_by(Run.created_at.desc(),Run.id.desc()).limit(1).with_for_update())
    if run is None:
        raise APIError(404,'GENERATION_NOT_FOUND')
    tasks=(await session.scalars(select(Task).where(Task.run_id == run.id).order_by(Task.id).with_for_update())).all()
    eligible=set(eligible_for_run(run,tasks))
    pages={str(p.id):p for p in await albums.album_pages(session,album_id)}
    assets={a.id:a for a in await albums.ready_assets(session,album_id)}
    grouped={}
    for task in tasks:
        grouped.setdefault(str(task.page_id),{})[task.stage]=task
    counts={'completed_pages':0,'unknown_pages':0,'failed_pages':0,'pending_pages':0}
    rows=[]
    for item in sorted(run.input_snapshot,key=lambda p:p['position']):
        page_id=item['page_id']; stages=grouped.get(page_id,{})
        page=pages.get(page_id)
        result=assets.get(page.result_asset_id) if page else None
        thumb=assets.get(page.thumbnail_asset_id) if page else None
        complete=(all(stage in stages and stages[stage].status == 'succeeded' for stage in STAGES)
            and page is not None and page.ai_caption is not None and bool(page.ai_caption.strip()) and page.caption_text is not None
            and result is not None and result.role == 'result' and result.page_id == page.id
            and thumb is not None and thumb.role == 'thumbnail' and thumb.page_id == page.id)
        bucket=('completed_pages' if complete else 'unknown_pages' if any(t.status=='unknown' for t in stages.values())
                else 'failed_pages' if any(t.status=='failed' for t in stages.values()) else 'pending_pages')
        counts[bucket]+=1
        rows.append({'page_id':page_id,'tasks':[{'stage':stage,'status':stages[stage].status,
            'completion_kind':stages[stage].completion_kind,'error_code':stages[stage].error_code,
            'retryable':stages[stage].id in eligible} for stage in STAGES if stage in stages]})
    total=len(rows)
    active=any(t.status=='running' or (t.status in {'queued','retry_wait'} and not t.requires_ai_call and t.has_persisted_input
        and (t.stage != 'optimize' or grouped.get(str(t.page_id),{}).get('image_transform') is not None
             and grouped[str(t.page_id)]['image_transform'].status == 'succeeded')) for t in tasks)
    poll=None if run.status in {'succeeded','cancelled'} or (run.status=='action_required' and not active) else 3000
    return {'run_id':str(run.id),'album_id':str(album.id),'album_status':album.status,'run_status':run.status,
        'generation_mode':run.config_snapshot.get('execution_mode') if run.config_snapshot.get('execution_mode') in {'local_fake','openai'} else None,
        'total_pages':total,**counts,'progress_percent':counts['completed_pages']*100//total if total else 0,
        'can_resume':bool(eligible),'poll_after_ms':poll,'pages':rows}
