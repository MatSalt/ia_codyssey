import {CaptionEditor} from './CaptionEditor';
import {ThumbnailStrip} from './ThumbnailStrip';
import {PhotoFrame} from '../../components/media/PhotoFrame';
import {BottomActionBar} from '../../components/layout/BottomActionBar';
import {ScreenHeader} from '../../components/layout/ScreenHeader';
import {GlassButton} from '../../components/ui/GlassButton';
import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, ApiError, errorText } from '../../api/client';
import type { Album, Detail, Page } from '../../api/types';
import { albumPath, captionValue, isDirty, requestIntents, savedDraft, type CaptionDraft } from '../generation/flow';
import { DevAiNotice } from '../generation/DevAiNotice';
import { usePrivateRequest } from '../generation/usePrivateRequest';
import { SignedPhoto } from '../viewer/SignedPhoto';
import { useSignedMedia } from '../viewer/useSignedMedia';
import { useUnsavedGuard } from './useUnsavedGuard';
import { reviewDrafts } from './drafts';
interface PageEdit extends CaptionDraft { saving?:boolean; message?:string; conflict?:{page:Page;details:Record<string,unknown>} }
const emptyAccess:Detail['media_access']=[];
export function ReviewEditor({userId}:{userId:string}) {
 const {albumId=''}=useParams();const navigate=useNavigate();const cache=useQueryClient();const request=usePrivateRequest();
 const queryKey=['album',userId,albumId];
 const detail=useQuery({queryKey,queryFn:({signal})=>api<Detail>(`/albums/${albumId}`,{signal}),retry:false,refetchOnWindowFocus:false});
 const [drafts,setDrafts]=useState<Record<string,PageEdit>>(()=>reviewDrafts.restore(userId,albumId));const draftsRef=useRef(drafts);draftsRef.current=drafts;
 const discarded=useRef(false);
 useEffect(()=>{if(!discarded.current)reviewDrafts.remember(userId,albumId,drafts);},[drafts,userId,albumId]);
 const saves=useRef(new Set<string>());const publishing=useRef(false);const [busy,setBusy]=useState(false);const [error,setError]=useState('');const [publishRejected,setPublishRejected]=useState(false);
 const scope=`${userId}:${albumId}:publish`;const pending=requestIntents.peek(scope);
 const [activePageId,setActivePageId]=useState<string|null>(null);
 const pages=detail.data?.detail.pages ?? [];
 const activePage=pages.find(p=>p.id===activePageId)??pages[0];
 const media=useSignedMedia(albumId,[...new Set(pages.flatMap(p=>[p.result?.asset_id,p.thumbnail?.asset_id]).filter((id):id is string=>!!id))],detail.data?.media_access ?? emptyAccess);
 useEffect(()=>{
  if(!detail.data)return;
  const {album,pages}=detail.data.detail;
  if(!['review_ready','published'].includes(album.status)){navigate(albumPath(album),{replace:true});return;}
  setDrafts(old=>{
   const next={...old};for(const page of pages){const draft=next[page.id];if(!draft || (!isDirty(draft) && !draft.saving && !draft.conflict))next[page.id]={text:page.caption_text??'',baseline:page.caption_text??'',version:page.version,message:draft?.message};else if(isDirty(draft) && !draft.saving && !draft.conflict && page.version!==draft.version)next[page.id]={...draft,conflict:{page,details:{resource_type:'page',resource_id:page.id,current_version:page.version}},message:'보관한 입력과 최신 서버 글귀를 비교해 주세요.'};}return next;
  });
 },[detail.data,navigate]);
 const dirty=Object.values(drafts).some(isDirty);
 const saving=Object.values(drafts).some(d=>d.saving);
 useUnsavedGuard(dirty,()=>{discarded.current=true;reviewDrafts.forget(userId,albumId);});
 function change(id:string,text:string) {setDrafts(old=>({...old,[id]:{...old[id],text,message:undefined}}));}
 async function save(id:string) {
  const draft=draftsRef.current[id];if(!draft || saves.current.has(id) || publishing.current || pending || !captionValue(draft.text).valid || draft.conflict)return;
  const sent=captionValue(draft.text).text;saves.current.add(id);setDrafts(old=>({...old,[id]:{...old[id],saving:true,message:undefined}}));
  try{
   const result=await api<{page:Page;album_version:number}>(`/albums/${albumId}/pages/${id}/caption`,{method:'PATCH',body:{caption_text:sent,expected_version:draft.version},signal:request.current.signal});
   if(request.current.signal.aborted)return;
   setDrafts(old=>({...old,[id]:{...savedDraft(old[id],sent,result.page),saving:false,message:'저장 완료'}}));
   cache.setQueryData<Detail>(queryKey,old=>old?{...old,detail:{...old.detail,album:{...old.detail.album,version:Math.max(old.detail.album.version,result.album_version)},pages:old.detail.pages.map(p=>p.id===id && p.version<=result.page.version?result.page:p)}}:old);
   void cache.invalidateQueries({queryKey:['viewer',userId,albumId]});void cache.invalidateQueries({queryKey:['albums',userId]});
  }catch(e){
   if(request.current.signal.aborted)return;
   setDrafts(old=>({...old,[id]:{...old[id],saving:false,message:errorText(e)}}));
   if(e instanceof ApiError && e.status===409){
    try{const fresh=await api<Detail>(`/albums/${albumId}`,{signal:request.current.signal});const server=fresh.detail.pages.find(p=>p.id===id);if(server)setDrafts(old=>({...old,[id]:{...old[id],conflict:{page:server,details:e.details}}}));cache.setQueryData(queryKey,fresh);}catch(fetchError){if(!request.current.signal.aborted)setError(errorText(fetchError));}
   }
  }finally{saves.current.delete(id);}
 }
 function discard(id:string) {
  const draft=draftsRef.current[id];if(!draft || draft.saving || busy || pending)return;
  if(!window.confirm('이 페이지의 저장하지 않은 입력을 버릴까요?'))return;
  const server=draft.conflict?.page;
  setDrafts(old=>({...old,[id]:{text:server?.caption_text??draft.baseline,baseline:server?.caption_text??draft.baseline,version:server?.version??draft.version,message:'저장된 글귀로 되돌렸습니다.'}}));
 }
 async function publish() {
  if(publishing.current || saves.current.size || Object.values(draftsRef.current).some(isDirty))return;
  publishing.current=true;setBusy(true);setError('');setPublishRejected(false);
  try{
   if(!requestIntents.peek(scope)){
    const latest=await api<Detail>(`/albums/${albumId}`,{signal:request.current.signal});
    if(latest.detail.album.status==='published'){navigate(`/albums/${albumId}/view`);return;}
    if(latest.detail.album.status!=='review_ready')throw new Error('모든 결과가 준비된 뒤 사진첩을 완성할 수 있습니다.');
    requestIntents.get(scope,{expected_version:latest.detail.album.version});
   }
   const intent=requestIntents.peek(scope)!;
   const result=await api<{album:Album}>(`/albums/${albumId}/publish`,{method:'POST',key:intent.key,body:intent.body,signal:request.current.signal});
   if(result.album.status!=='published')throw new Error('서버에서 사진첩 완성을 확인하지 못했습니다.');
   requestIntents.finish(scope);await cache.invalidateQueries({queryKey:['albums',userId]});void cache.invalidateQueries({queryKey});navigate(`/albums/${albumId}/view`);
  }catch(e){
   if(request.current.signal.aborted)return;setError(errorText(e));
   try{const fresh=await api<Detail>(`/albums/${albumId}`,{signal:request.current.signal});cache.setQueryData(queryKey,fresh);
    if(fresh.detail.album.status==='published'){requestIntents.finish(scope);await cache.invalidateQueries({queryKey:['albums',userId]});navigate(`/albums/${albumId}/view`);return;}
    if(e instanceof ApiError && e.status===409)setPublishRejected(true);
   }catch(fetchError){if(!request.current.signal.aborted)setError(`${errorText(e)} ${errorText(fetchError)}`);}
  }finally{publishing.current=false;if(!request.current.signal.aborted)setBusy(false);}
 }
 if(detail.isPending)return <p role="status">저장된 결과를 불러오는 중…</p>;
 if(!detail.data)return <section><Link to="/albums">← 나의 책장</Link><p role="alert">{errorText(detail.error)}</p><button onClick={()=>void detail.refetch()}>결과 다시 불러오기</button></section>;
 const album=detail.data.detail.album;
 if(!['review_ready','published'].includes(album.status))return <p role="status">현재 사진첩 상태를 확인합니다…</p>;
 const page=activePage;const draft=page?drafts[page.id]:undefined;
 const value=captionValue(draft?.text??'');const asset=(page?.result??page?.thumbnail)?.asset_id;
 const finish=album.status==='published'?<Link className="button-link mori-button" to={`/albums/${albumId}/view`}>사진첩 감상</Link>:<GlassButton disabled={busy||dirty||saving||!!Object.values(drafts).find(d=>d.conflict)} onClick={()=>void publish()}>{busy?'완성 확인 중…':pending?'같은 완성 요청 다시 확인':'사진첩 완성'}</GlassButton>;
 return <section className="review-screen concept-review"><ScreenHeader title="사진첩 확인" leading={<Link className="mori-icon-button" to="/albums" aria-label="책장으로">‹</Link>} trailing={<span>{page?.position??0} / {pages.length}</span>}/>
<DevAiNotice mode={detail.data?.detail.generation_mode ?? null}/><details className="review-help"><summary>글귀 편집 안내</summary><p className="hint">페이지마다 저장 버튼을 눌러 주세요. 빈 글귀도 저장할 수 있습니다. 한글 조합을 정리한 뒤 최대 80자입니다.</p></details>{dirty && <p className="notice" role="status">저장하지 않은 글귀가 있습니다. 각 페이지를 저장하거나 ‘입력 버리기’를 선택한 뒤 사진첩을 완성해 주세요.</p>}{saving && <p role="status">글귀를 저장하는 동안 완성할 수 없습니다.</p>}{error && <p role="alert">{error}</p>}{pending && !busy && <div className="notice"><p>완성 응답을 확인하지 못했습니다. 입력을 잠시 잠그고 보낸 키·버전으로 결과를 다시 확인합니다.</p>{publishRejected && <button className="secondary" onClick={()=>{requestIntents.finish(scope);setPublishRejected(false);setError('최신 서버 내용을 확인했습니다. 완성 버튼으로 새 요청을 준비할 수 있습니다.');}}>거절된 요청 닫고 최신 내용 확인</button>}</div>}{media.error && <p role="alert">{media.error} <button className="secondary" onClick={()=>void media.refresh()}>사진 주소 다시 받기</button></p>}
 {page&&draft?<div className="review-current"><PhotoFrame><SignedPhoto access={media.access.find(a=>a.asset_id===asset)} alt={`${page.position}번째 생성 사진`} onFailure={media.failed} retry={()=>asset&&void media.refresh([asset])}/></PhotoFrame><CaptionEditor value={draft.text} count={value.count} disabled={!!draft.saving||busy||!!pending} invalid={!value.valid} onChange={text=>change(page.id,text)} actions={<><GlassButton disabled={!isDirty(draft)||!value.valid||draft.saving||busy||!!pending||!!draft.conflict} onClick={()=>void save(page.id)}>{draft.saving?'저장 중…':'이 글귀 저장'}</GlassButton><button className="secondary" disabled={!isDirty(draft)&&!draft.conflict||draft.saving||busy||!!pending} onClick={()=>discard(page.id)}>입력 버리기</button></>} feedback={<>{draft.conflict && <div className="conflict" role="alert"><p>다른 변경이 반영되었습니다. 입력은 그대로 보존했습니다.</p><p>서버에 저장된 글귀: <q>{draft.conflict.page.caption_text || '(빈 글귀)'}</q></p><p>서버 페이지 버전: {String(draft.conflict.details.current_version??draft.conflict.page.version)}</p><button className="secondary" disabled={busy||!!pending} onClick={()=>setDrafts(old=>({...old,[page.id]:{...old[page.id],baseline:draft.conflict!.page.caption_text??'',version:draft.conflict!.page.version,conflict:undefined,message:'내 입력을 보존했습니다. 저장 버튼을 눌러 최신 버전에 저장하세요.'}}))}>내 입력 유지하고 최신 버전 사용</button></div>}{draft.message && <p role={draft.message==='저장 완료'?'status':'alert'}>{draft.message}</p>}</>}/></div>:<p role="status">검토할 사진을 준비하고 있어요.</p>}
 <ThumbnailStrip activeId={page?.id??''} onSelect={setActivePageId} items={pages.map(p=>{const id=(p.thumbnail??p.result)?.asset_id;const access=media.access.find(a=>a.asset_id===id);return {id:p.id,label:`${p.position}번째 사진`,dirty:!!drafts[p.id]&&(isDirty(drafts[p.id])||!!drafts[p.id].conflict),content:access?<img src={access.url} alt="" onError={()=>media.failed(access)}/>:<span>{p.position}</span>};})}/>
 <BottomActionBar>{finish}</BottomActionBar></section>;
}
