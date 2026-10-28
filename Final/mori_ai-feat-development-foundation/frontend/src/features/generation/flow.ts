import type { Album, GenerationView, MediaAccess, ViewerPage } from '../../api/types';

export function albumPath(album: Pick<Album,'id'|'status'>): string {
 const screen=album.status==='published'?'view':album.status==='review_ready'?'review':album.status==='processing'||album.status==='action_required'?'progress':'edit';
 return `/albums/${album.id}/${screen}`;
}
export function pollInterval(view: Pick<GenerationView,'run_status'|'poll_after_ms'>|undefined, visible:boolean): number|false {
 return visible && view && !['succeeded','cancelled'].includes(view.run_status) && view.poll_after_ms !== null ? Math.max(500,view.poll_after_ms) : false;
}
export function captionValue(value:string) {const text=value.normalize('NFC'); const count=Array.from(text).length;return {text,count,valid:count<=80};}
export interface CaptionDraft { text:string; baseline:string; version:number }
export function savedDraft(draft:CaptionDraft,sent:string,page:{caption_text:string|null;version:number}):CaptionDraft {
 const baseline=page.caption_text ?? '';
 return {text:captionValue(draft.text).text===sent?baseline:draft.text,baseline,version:page.version};
}
export function isDirty(draft:CaptionDraft) {return captionValue(draft.text).text!==draft.baseline;}
interface Intent { key:string; body:Readonly<Record<string,unknown>> }
export class RequestIntents {
 private entries=new Map<string,Intent>();
 get(scope:string,body:Record<string,unknown>):Intent {
  let intent=this.entries.get(scope);
  if(!intent){intent={key:crypto.randomUUID(),body:Object.freeze({...body})};this.entries.set(scope,intent);}
  return intent;
 }
 peek(scope:string) {return this.entries.get(scope);}
 finish(scope:string) {this.entries.delete(scope);}
 clear() {this.entries.clear();}
}
export const requestIntents=new RequestIntents();
export function neededMedia(pages:Pick<ViewerPage,'image'>[],index:number,access:MediaAccess[],now=Date.now()):string[] {
 return pages.slice(index,index+2).map(p=>p.image.asset_id).filter(id=>!access.some(a=>a.asset_id===id && Date.parse(a.expires_at)>now+10000));
}
export function currentPageIndex(pages:Pick<ViewerPage,'id'>[],id:string|null) {return Math.max(0,pages.findIndex(p=>p.id===id));}
export function nextPageIndex(index:number,offset:number,total:number) {return Math.max(0,Math.min(Math.max(0,total-1),index+offset));}
export function swipeOffset(dx:number,dy:number) {return Math.abs(dx)>=45 && Math.abs(dx)>Math.abs(dy)*1.4 ? dx<0?1:-1 : 0;}
// A page turn during renewal queues the newest request instead of dropping it.
export class MediaRenewals {
 private running=false;
 private queued:(()=>Promise<void>)|null=null;
 get busy(){return this.running;}
 async run<T>(needed:()=>string[],send:(ids:string[])=>Promise<T>,accept:(value:T)=>void):Promise<void> {
  if(this.running){this.queued=()=>this.run(needed,send,accept);return;}
  this.running=true;
  try{const ids=needed();if(ids.length)accept(await send(ids));}
  finally{this.running=false;const next=this.queued;this.queued=null;if(next)await next();}
 }
}
export function keyboardOffset(key:string,modified:boolean,editing:boolean):number {
 return modified||editing?0:key==='ArrowLeft'?-1:key==='ArrowRight'?1:0;
}
