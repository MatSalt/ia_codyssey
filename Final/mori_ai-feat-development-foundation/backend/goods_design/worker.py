"""Bounded goods lane; unknown paid calls never re-dispatch."""
import asyncio
from datetime import timedelta
from io import BytesIO
from decimal import Decimal
from backend.storage.factory import result_store
from sqlalchemy import select,func
from PIL import Image,ImageOps
from backend.goods_design.models import GoodsWork,GoodsRevision,GoodsDesign
from backend.goods_design.service import now
from backend.models import Task
from backend.generation.repository import lock_claims
from backend.generation.budget import BudgetLedger,BudgetExceeded
from backend.generation.openai_provider import ProviderFailure,IMAGE_RESERVATION_USD

class GoodsWorker:
    def __init__(self,sessions,store,settings,provider=None):
        self.sessions,self.store,self.settings=sessions,store,settings
        self.receipts=result_store(store)
        self.provider=provider
        if settings.ai_real_calls_enabled and provider is None:
            from backend.goods_design.provider import GoodsProvider
            self.provider=GoodsProvider(settings)
        self.ledger=BudgetLedger(sessions,settings.ai_validation_initial_budget_usd,settings.ai_validation_budget_usd)

    async def run_once(self):
        await self.maintenance()
        async with self.sessions() as s,s.begin():
            await lock_claims(s)
            count=await s.scalar(select(func.count()).select_from(Task).where(Task.stage=='image_transform',Task.status=='running',Task.lease_until>now()))
            count+=await s.scalar(select(func.count()).select_from(GoodsRevision).where(GoodsRevision.status=='running',GoodsRevision.lease_until>now()))
            if count>=2:return False
            # Lock the parent before revision, same order as admission/discard.
            w=await s.scalar(select(GoodsWork).where(GoodsWork.status=='active',GoodsWork.expires_at>now(),GoodsWork.id.in_(select(GoodsRevision.work_id).where(GoodsRevision.status=='queued',GoodsRevision.config['mode'].astext==('real' if self.settings.ai_real_calls_enabled else 'fake')))).order_by(GoodsWork.created_at).with_for_update(skip_locked=True).limit(1))
            if w is None:return False
            r=await s.scalar(select(GoodsRevision).where(GoodsRevision.work_id==w.id,GoodsRevision.status=='queued').order_by(GoodsRevision.created_at).with_for_update().limit(1))
            real=r.config.get('mode')=='real'
            if real!=self.settings.ai_real_calls_enabled:return False
            r.status='running';r.lease_until=now()+timedelta(seconds=600)
            rid,wid,source_key=r.id,w.id,w.source_key
            output=f'{w.owner_id}/{w.id}/{r.id}/result'
            parent=await s.get(GoodsRevision,r.parent_id) if r.parent_id else None
            parent_key=parent.result_key if parent else None
            prompt,model=r.prompt,r.config['model']
        reserved=False;dispatched=False
        try:
            source=await asyncio.to_thread(self.store.read_bytes,source_key)
            previous=await asyncio.to_thread(self.store.read_bytes,parent_key) if parent_key else None
            if real:
                reserved=await self.ledger.reserve(rid,IMAGE_RESERVATION_USD)
                if not reserved:raise ProviderFailure('AI_RESULT_UNKNOWN')
                # Discard before dispatch must not cause a paid call.
                async with self.sessions() as s,s.begin():
                    w=await s.scalar(select(GoodsWork).where(GoodsWork.id==wid).with_for_update())
                    if w.status!='active' or w.expires_at<=now():
                        await self.ledger.release_unsent(rid)
                        r=await s.get(GoodsRevision,rid);r.status='cancelled';return True
                dispatched=True
                result=await asyncio.wait_for(self.provider.generate(source,previous,prompt,model),timeout=310)
                data=result.image
                # Save output before settlement; a ledger outage must not trigger regeneration.
                await asyncio.to_thread(self.store.write,output,data)
                await self.receipts.save(str(rid),{'goods_accounting':True,'actual_usd':str(result.cost_usd) if result.cost_usd is not None else None,'usage':result.usage,'request_id':result.request_id})
                await self.ledger.settle(rid,result.cost_usd,result.usage,result.request_id)
            else:
                def fake():
                    with Image.open(BytesIO(previous or source)) as im:
                        im=ImageOps.contain(im.convert('RGBA'),(700,700))
                        canvas=Image.new('RGBA',(768,768));canvas.alpha_composite(im,((768-im.width)//2,(768-im.height)//2))
                        out=BytesIO();canvas.save(out,format='PNG');return out.getvalue()
                data=await asyncio.to_thread(fake)
                await asyncio.to_thread(self.store.write,output,data)
            async with self.sessions() as s,s.begin():
                w=await s.scalar(select(GoodsWork).where(GoodsWork.id==wid).with_for_update())
                r=await s.get(GoodsRevision,rid)
                if w.status=='active' and w.expires_at>now():r.status='ready';r.result_key=output;r.error_code=None
                else:r.status='cancelled'
                r.lease_until=None
                abandoned=r.status=='cancelled'
            if abandoned:await asyncio.to_thread(self.store.delete,output)
        except asyncio.CancelledError:raise
        except Exception as exc:
            unknown=real and dispatched and not(isinstance(exc,ProviderFailure) and exc.dispatch_state in ('not_sent','rejected','responded'))
            if reserved:
                if not dispatched or isinstance(exc,ProviderFailure) and exc.dispatch_state in ('not_sent','rejected'):await self.ledger.release_unsent(rid)
                else:await self.ledger.settle(rid,getattr(exc,'cost_usd',None),getattr(exc,'usage',{}),getattr(exc,'request_id',None))
            async with self.sessions() as s,s.begin():
                w=await s.scalar(select(GoodsWork).where(GoodsWork.id==wid).with_for_update())
                r=await s.get(GoodsRevision,rid)
                r.status='unknown' if unknown else 'failed';r.lease_until=None
                r.error_code='AI_BUDGET_EXCEEDED' if isinstance(exc,BudgetExceeded) else 'AI_RESULT_UNKNOWN' if unknown else 'AI_TEMPORARY_FAILURE'
        return True

    async def maintenance(self):
        async with self.sessions() as s,s.begin():
            rows=(await s.scalars(select(GoodsRevision).where(GoodsRevision.status=='running',GoodsRevision.lease_until<=now()).with_for_update(skip_locked=True).limit(20))).all()
            for r in rows:r.status='unknown';r.error_code='AI_RESULT_UNKNOWN';r.lease_until=None
        # Recover original stored output only, never repeat the provider request.
        async with self.sessions() as s:
            ids=list(await s.scalars(select(GoodsRevision.id).where(GoodsRevision.status=='unknown').limit(20)))
        for rid in ids:
            async with self.sessions() as s:
                r=await s.get(GoodsRevision,rid);w=await s.get(GoodsWork,r.work_id)
                key=f'{w.owner_id}/{w.id}/{r.id}/result';wid=w.id
            receipt=await self.receipts.load(str(rid))
            if receipt and receipt.get('goods_accounting'):
                await self.ledger.settle(rid,Decimal(receipt['actual_usd']) if receipt.get('actual_usd') is not None else None,receipt.get('usage',{}),receipt.get('request_id'))
            if await asyncio.to_thread(self.store.exists,key):
                async with self.sessions() as s,s.begin():
                    w=await s.scalar(select(GoodsWork).where(GoodsWork.id==wid).with_for_update())
                    r=await s.get(GoodsRevision,rid)
                    if r.status=='unknown' and w.status=='active' and w.expires_at>now():r.status='ready';r.result_key=key;r.error_code=None
        async with self.sessions() as s:
            ids=list(await s.scalars(select(GoodsWork.id).where((GoodsWork.status=='discarded')|((GoodsWork.status=='active')&(GoodsWork.expires_at<=now()))).limit(20)))
        for wid in ids:
            async with self.sessions() as s,s.begin():
                w=await s.scalar(select(GoodsWork).where(GoodsWork.id==wid).with_for_update())
                if w.status=='completed':continue
                w.status='discarded'
                rows=(await s.scalars(select(GoodsRevision).where(GoodsRevision.work_id==wid))).all()
                if any(r.status=='running' for r in rows):continue
                keys=[w.source_key] if w.source_key else []
                keys += [f'{w.owner_id}/{w.id}/{r.id}/result' for r in rows]
                for key in keys:await asyncio.to_thread(self.store.delete,key)
                w.source_key=None;w.source_hash=None;w.status='cleaned'
                for r in rows:r.status='cancelled';r.message='';r.prompt='';r.result_key=None
