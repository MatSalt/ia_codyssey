import {GlassButton} from '../../components/ui/GlassButton';
import {UploadPhotoCard} from '../uploads/UploadPhotoCard';
import {ScreenHeader} from '../../components/layout/ScreenHeader';
import {BottomActionBar} from '../../components/layout/BottomActionBar';
import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, ApiError, errorText } from '../../api/client';
import type { Detail, MediaAccess, Page, DevConfig, GenerationAccepted } from '../../api/types';
import { UploadPanel } from '../uploads/UploadPanel';
import { albumPath, requestIntents } from '../generation/flow';
import { DevAiNotice } from '../generation/DevAiNotice';
import { usePrivateRequest } from '../generation/usePrivateRequest';
const labels: Record<string,string>={reserved:'전송 대기',validating:'사진 검증·정규화 중',ready:'준비 완료',rejected:'검증 실패 · 삭제 후 다시 첨부',expired:'업로드 만료 · 삭제 후 다시 첨부'};
function Photo({page,access,renew}:{page:Page;access?:MediaAccess;renew:()=>void}) {
 const [failed,setFailed]=useState(false);
 useEffect(()=>setFailed(false),[access?.url]);
 return <div className="photo">{page.upload_status==='ready' && access && !failed ? <img src={access.url} alt={`${page.position}번째 사진`} onError={()=>{setFailed(true);renew();}}/> : <div className="placeholder"><span aria-hidden="true">▧</span><span>{labels[page.upload_status]}</span>{failed && <button className="secondary" onClick={renew}>미리보기 다시 불러오기</button>}</div>}</div>;
}
export function AlbumEditor({userId}:{userId:string}) {
 const {albumId=''}=useParams(); const navigate=useNavigate(); const cache=useQueryClient();
 const request=usePrivateRequest();const generationLock=useRef(false);const [rejected,setRejected]=useState(false);const scope=`${userId}:${albumId}:generation`;
 const dev=useQuery({queryKey:['dev-config'],queryFn:({signal})=>api<DevConfig>('/api/dev/config',{signal}),retry:false});
 const [error,setError]=useState(''); const [busy,setBusy]=useState(false); const [visible,setVisible]=useState(!document.hidden);
 const queryKey=['album',userId,albumId];
 const detail=useQuery({queryKey,queryFn:({signal})=>api<Detail>(`/albums/${albumId}`,{signal}),refetchInterval:q=>visible && q.state.data?.detail.pages.some(p=>['reserved','validating'].includes(p.upload_status)) ? 1800 : false,refetchIntervalInBackground:false});
 const data=detail.data;
 useEffect(()=>{if(data && data.detail.album.status!=='draft')navigate(albumPath(data.detail.album),{replace:true});},[data?.detail.album.status,albumId,navigate]);
 useEffect(()=>{const changed=()=>{setVisible(!document.hidden);if(!document.hidden)void detail.refetch();};document.addEventListener('visibilitychange',changed);return()=>document.removeEventListener('visibilitychange',changed);},[albumId]);
 async function renew() {
  if(!data)return; const ids=data.detail.pages.filter(p=>p.upload_status==='ready').map(p=>(p.thumbnail ?? p.source)?.asset_id).filter((id):id is string=>!!id);
  if(!ids.length)return;
  try {const result=await api<{media_access:MediaAccess[]}>(`/albums/${albumId}/media-access`,{method:'POST',body:{asset_ids:ids},signal:request.current.signal});if(request.current.signal.aborted)return;cache.setQueryData<Detail>(queryKey,old=>old?{...old,media_access:result.media_access}:old);}catch(e){if(!request.current.signal.aborted)setError(errorText(e));}
 }
 useEffect(()=>{
  if(!visible || !data?.media_access.length)return;
  const expires=Math.min(...data.media_access.map(a=>Date.parse(a.expires_at)));
  const timer=window.setTimeout(()=>void renew(),Math.max(1000,expires-Date.now()-10000));return()=>window.clearTimeout(timer);
 },[data,visible]);
 async function mutate(fn:(fresh:Detail)=>Promise<unknown>) {if(busy)return;setBusy(true);setError('');try{const fresh=await api<Detail>(`/albums/${albumId}`,{signal:request.current.signal});await fn(fresh);if(request.current.signal.aborted)return;await detail.refetch();await cache.invalidateQueries({queryKey:['albums',userId]});}catch(e){if(!request.current.signal.aborted){setError(errorText(e));await detail.refetch();}}finally{if(!request.current.signal.aborted)setBusy(false);}}
 if(detail.isPending)return <p role="status">사진첩을 불러오는 중…</p>;
 if(!data)return <section><Link to="/albums">← 책장</Link><p role="alert">{errorText(detail.error)}</p><button onClick={()=>void detail.refetch()}>다시 불러오기</button></section>;
 const {album,pages,order_mode}=data.detail;
 if(album.status!=='draft')return <p role="status">현재 사진첩으로 이동하는 중…</p>;
 const pending=requestIntents.peek(scope);
 async function generate(){
  if(generationLock.current || busy)return;generationLock.current=true;setBusy(true);setError('');setRejected(false);
  try{
   if(!requestIntents.peek(scope)){const fresh=await api<Detail>(`/albums/${albumId}`,{signal:request.current.signal});if(!fresh.detail.pages.length||fresh.detail.pages.some(p=>p.upload_status!=='ready'))throw new Error('모든 사진 검증이 끝난 뒤 생성할 수 있습니다.');requestIntents.get(scope,{expected_version:fresh.detail.album.version});}
   const intent=requestIntents.peek(scope)!;await api<GenerationAccepted>(`/albums/${albumId}/generation`,{method:'POST',body:intent.body,key:intent.key,signal:request.current.signal});if(request.current.signal.aborted)return;requestIntents.finish(scope);await cache.invalidateQueries({queryKey:['albums',userId]});navigate(`/albums/${albumId}/progress`);
  }catch(e){if(!request.current.signal.aborted){setError(errorText(e));setRejected(e instanceof ApiError && e.status>=400 && e.status<500 && e.status!==401);await detail.refetch();}}finally{generationLock.current=false;if(!request.current.signal.aborted)setBusy(false);}
 }
 async function move(id:string,offset:number) {await mutate(async fresh=>{const ids=fresh.detail.pages.map(p=>p.id);const index=ids.indexOf(id);const next=index+offset;if(index<0 || next<0 || next>=ids.length)return;[ids[index],ids[next]]=[ids[next],ids[index]];await api(`/albums/${albumId}/page-order`,{method:'PUT',body:{page_ids:ids,expected_version:fresh.detail.album.version},signal:request.current.signal});});}
 return <section className="album-editor"><Link className="mori-icon-button" to="/albums" aria-label="책장으로">‹</Link><ScreenHeader title="사진 고르기" subtitle="사진 한 장이 한 페이지가 돼요"/><div className="upload-heading-tools"><span className="sort-state">{order_mode==='manual'?'직접 정한 순서':'날짜순'} · {pages.length}장</span><details className="album-management"><summary aria-label="사진첩 관리">···</summary><button className="danger secondary" disabled={busy} onClick={()=>{if(window.confirm('사진첩과 모든 사진을 삭제할까요?'))void mutate(async fresh=>{await api(`/albums/${albumId}?expected_version=${fresh.detail.album.version}`,{method:'DELETE',signal:request.current.signal});navigate('/albums');});}}>사진첩 삭제</button></details></div>{error && <p role="alert">{error} 선택한 로컬 파일은 유지됩니다.</p>}<DevAiNotice/>{pending && <div className="notice"><p>생성 요청을 보냈습니다. 응답이 없으면 같은 키·버전으로 다시 확인합니다.</p>{rejected && <button className="secondary" onClick={()=>{requestIntents.finish(scope);setRejected(false);setError('거절된 생성 요청을 닫았습니다. 사진을 확인한 뒤 다시 생성해 주세요.');}}>거절된 요청 닫기</button>}</div>}{dev.data?.generation_enabled!==true && <p className="notice">사진첩 생성이 현재 비활성화되어 있습니다.</p>}{pages.some(p=>p.upload_status==='reserved'||p.upload_status==='validating') && <p className="notice" role="status">검증 중에는 순서가 임시로 표시됩니다. 직접 이동한 순서는 유지됩니다.</p>}{pages.length===0 && <div className="empty"><h2>아직 담은 사진이 없어요</h2><p>아래 사진 추가 버튼으로 좋아하는 순간을 담아 보세요.</p></div>}<ol className="pages">{pages.map((page,index)=><UploadPhotoCard key={page.id} position={index+1} photo={<Photo page={page} access={data.media_access.find(a=>a.asset_id===(page.thumbnail ?? page.source)?.asset_id)} renew={()=>void renew()}/>} status={labels[page.upload_status]} actions={<><button className="secondary" disabled={busy||!!pending||index===0} aria-label={`${index+1}번째 사진 앞으로 이동`} onClick={()=>void move(page.id,-1)}>앞으로</button><button className="secondary" disabled={busy||!!pending||index===pages.length-1} aria-label={`${index+1}번째 사진 뒤로 이동`} onClick={()=>void move(page.id,1)}>뒤로</button><button className="text danger" disabled={busy||!!pending} aria-label={`${index+1}번째 사진 삭제`} onClick={()=>{if(window.confirm('이 사진을 삭제할까요? 실패한 사진은 삭제한 뒤 다시 첨부할 수 있습니다.'))void mutate(fresh=>api(`/albums/${albumId}/pages/${page.id}?expected_version=${fresh.detail.album.version}`,{method:'DELETE',signal:request.current.signal}));}}>삭제</button></>}/>)}</ol>{!pending && <UploadPanel key={albumId} albumId={albumId} userId={userId} refresh={()=>detail.refetch()}/>}<BottomActionBar><GlassButton disabled={busy||dev.data?.generation_enabled!==true||!pages.length||pages.some(p=>p.upload_status!=='ready')} onClick={()=>void generate()}>{busy?'접수 중…':pending?'같은 생성 요청 다시 확인':`${pages.filter(p=>p.upload_status==='ready').length}장으로 사진첩 만들기`}</GlassButton></BottomActionBar></section>;
}
