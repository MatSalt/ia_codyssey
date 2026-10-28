import {PhotoStack} from './PhotoStack';
import {GenerationSteps} from './GenerationSteps';
import {generationSteps} from './steps';
import {SignedPhoto} from '../viewer/SignedPhoto';
import {useSignedMedia} from '../viewer/useSignedMedia';
import {BottomActionBar} from '../../components/layout/BottomActionBar';
const emptyAccess:Detail['media_access']=[];
import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, ApiError, errorText } from '../../api/client';
import type { Detail, DevConfig, GenerationAccepted, GenerationView, TaskView } from '../../api/types';
import { albumPath, pollInterval, requestIntents } from './flow';
import { DevAiNotice } from './DevAiNotice';
import { useVisibility } from './useVisibility';
import { usePrivateRequest } from './usePrivateRequest';
const stageLabels:Record<TaskView['stage'],string>={caption:'글귀 만들기',image_transform:'3:4 사진 만들기',optimize:'감상용 사진 준비'};
const taskLabels:Record<TaskView['status'],string>={queued:'대기',running:'진행 중',retry_wait:'재시도 대기',succeeded:'완료',failed:'실패',unknown:'결과 확인 불가',cancelled:'취소'};
export function GenerationProgress({userId}:{userId:string}) {
 const {albumId=''}=useParams();const navigate=useNavigate();const cache=useQueryClient();const request=usePrivateRequest();
 const dev=useQuery({queryKey:['dev-config'],queryFn:({signal})=>api<DevConfig>('/api/dev/config',{signal}),retry:false});
 const [resumeRejected,setResumeRejected]=useState(false);
 const [error,setError]=useState('');const [busy,setBusy]=useState(false);const lock=useRef(false);
 const [visible,setVisible]=useState(!document.hidden);
 const progress=useQuery({queryKey:['generation',userId,albumId],queryFn:({signal})=>api<GenerationView>(`/albums/${albumId}/generation`,{signal}),retry:false,refetchInterval:q=>pollInterval(q.state.data,visible),refetchIntervalInBackground:false,refetchOnWindowFocus:false});
 const visibility=useVisibility(()=>void progress.refetch());
 useEffect(()=>setVisible(visibility),[visibility]);
 const view=progress.data;
 const albumPreview=useQuery({queryKey:['album-preview',userId,albumId],queryFn:({signal})=>api<Detail>(`/albums/${albumId}`,{signal}),retry:false,refetchOnWindowFocus:false});
 const previewAssets=(albumPreview.data?.detail.pages??[]).slice(0,3).map(p=>(p.thumbnail??p.source)?.asset_id).filter((id):id is string=>!!id);
 const previewMedia=useSignedMedia(albumId,previewAssets,albumPreview.data?.media_access??emptyAccess);

 useEffect(()=>{if(view?.album_status==='review_ready'||view?.album_status==='published'){void cache.invalidateQueries({queryKey:['album',userId,albumId]});void cache.invalidateQueries({queryKey:['albums',userId]});navigate(albumPath({id:albumId,status:view.album_status}),{replace:true});}},[view?.album_status,albumId,userId,cache,navigate]);
 async function resume() {
  if(lock.current || !view?.can_resume || dev.data?.generation_enabled!==true)return;lock.current=true;setBusy(true);setError('');setResumeRejected(false);
  const scope=`${userId}:${albumId}:resume`;
  try {
   if(!requestIntents.peek(scope)){const latest=await api<Detail>(`/albums/${albumId}`,{signal:request.current.signal});requestIntents.get(scope,{run_id:view.run_id,expected_version:latest.detail.album.version});}
   const intent=requestIntents.peek(scope)!;
   await api<GenerationAccepted>(`/albums/${albumId}/generation/resume`,{method:'POST',body:intent.body,key:intent.key,signal:request.current.signal});
   requestIntents.finish(scope);await progress.refetch();await cache.invalidateQueries({queryKey:['albums',userId]});
  }catch(e){if(!request.current.signal.aborted){setError(errorText(e));setResumeRejected(e instanceof ApiError && e.status>=400 && e.status<500 && e.status!==401);await progress.refetch();}}finally{lock.current=false;if(!request.current.signal.aborted)setBusy(false);}
 }
 async function remove() {
  if(lock.current || !window.confirm('사진첩과 모든 사진을 삭제할까요? 삭제하면 진행 중인 작업도 종료됩니다.'))return;
  lock.current=true;setBusy(true);setError('');
  try{const latest=await api<Detail>(`/albums/${albumId}`,{signal:request.current.signal});await api(`/albums/${albumId}?expected_version=${latest.detail.album.version}`,{method:'DELETE',signal:request.current.signal});await cache.invalidateQueries({queryKey:['albums',userId]});navigate('/albums');}catch(e){if(!request.current.signal.aborted)setError(errorText(e));}finally{lock.current=false;if(!request.current.signal.aborted)setBusy(false);}
 }
 return <section className="generation-screen"><Link className="mori-icon-button" to="/albums" aria-label="책장으로">‹</Link><div className="section-heading"><div><span className="generation-brand">mori</span><h1>추억을 엮고 있어요</h1><p>사진과 한 문장을 차곡차곡 담고 있어요.</p></div><details className="album-management"><summary aria-label="사진첩 관리">···</summary><button className="secondary danger" disabled={busy} onClick={()=>void remove()}>사진첩 삭제</button></details></div><DevAiNotice mode={view?.generation_mode ?? null}/>{error && <p role="alert">{error} 요청 응답이 없으면 같은 키·버전으로 다시 시도합니다.</p>}{progress.isPending && <p role="status">실제 진행 상태를 불러오는 중…</p>}{progress.isError && <div role="alert"><p>{errorText(progress.error)}</p><button className="secondary" onClick={()=>void progress.refetch()}>진행 상태 다시 확인</button></div>}{view && <><PhotoStack photos={previewAssets.map(id=><SignedPhoto key={id} access={previewMedia.access.find(a=>a.asset_id===id)} alt="" onFailure={previewMedia.failed} retry={()=>void previewMedia.refresh([id])}/>)}/><div className="progress-summary"><p role="status">전체 {view.total_pages}장 중 {view.completed_pages}장 완료 · {view.progress_percent}%</p><progress value={view.completed_pages} max={Math.max(1,view.total_pages)} aria-label="완료한 사진 수"/><dl className="progress-counts"><div><dt>완료</dt><dd>{view.completed_pages}</dd></div><div><dt>결과 확인 불가</dt><dd>{view.unknown_pages}</dd></div><div><dt>실패</dt><dd>{view.failed_pages}</dd></div><div><dt>대기·진행</dt><dd>{view.pending_pages}</dd></div></dl></div><GenerationSteps steps={generationSteps(view)}/>{view.unknown_pages>0 && <p className="notice">일부 요청의 결과를 확인할 수 없어 자동으로 새 AI 요청을 보내지 않습니다. 원래 결과 확인을 기다리거나 사진첩을 삭제할 수 있습니다.</p>}{view.failed_pages>0 && <p className="notice">실패한 단계가 있습니다. 서버가 안전하게 재개할 수 있다고 확인한 경우에만 이어서 진행할 수 있습니다.</p>}{view.can_resume && <button disabled={busy||dev.data?.generation_enabled!==true} onClick={()=>void resume()}>{busy?'재개 접수 중…':requestIntents.peek(`${userId}:${albumId}:resume`)?'같은 재개 요청 다시 시도':'안전한 단계 이어서 진행'}</button>}{resumeRejected && requestIntents.peek(`${userId}:${albumId}:resume`) && <button className="secondary" disabled={busy} onClick={()=>{requestIntents.finish(`${userId}:${albumId}:resume`);setResumeRejected(false);setError('거절된 재개 요청을 닫았습니다. 최신 상태를 확인한 뒤 다시 이어서 진행할 수 있습니다.');}}>거절된 재개 요청 닫기</button>}{view.run_status==='cancelled' && <p className="notice">이 작업은 취소되었습니다.</p>}<button className="text" disabled={busy||progress.isFetching} onClick={()=>void progress.refetch()}>현재 상태 새로고침</button><details className="generation-detail"><summary>사진별 진행 상태</summary><ol className="task-pages">{view.pages.map((page,index)=><li key={page.page_id}><h2>{index+1}번째 사진</h2><ul>{page.tasks.map(task=><li key={task.stage}><span>{stageLabels[task.stage]}</span><strong className={`task-status ${task.status}`}>{taskLabels[task.status]}{task.completion_kind==='passthrough'?' · 원본 3:4 유지':''}</strong>{task.error_code && <span className="task-error">{task.error_code}{task.retryable?' · 안전한 재개 가능':''}</span>}</li>)}</ul></li>)}</ol></details><p className="generation-continue">책장으로 이동해도 계속 만들어요</p><BottomActionBar><Link className="button-link" to="/albums">책장으로</Link></BottomActionBar></>}</section>;
}
