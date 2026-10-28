import {useEffect,useRef,useState} from 'react';
import {Link,useBlocker} from 'react-router';
import {useQuery} from '@tanstack/react-query';
import {api,errorText} from '../../api/client';
import {GlassButton} from '../../components/ui/GlassButton';
import {GlassPanel} from '../../components/ui/GlassPanel';
import {ScreenHeader} from '../../components/layout/ScreenHeader';
import {BottomActionBar} from '../../components/layout/BottomActionBar';
import {StylePicker} from './design/StylePicker';
import type {DesignStyle,StyleId} from './design/catalog';
import {RevisionHistory} from './design/RevisionHistory';
import {GoodsMockup} from './mockup/GoodsMockup';
import {previewKey} from './mockup/preview';
import type {Placement} from './mockup/preview';
import type {GoodsRevision,GoodsDesign} from './api';
import {abandon,uploadSource} from './api';
import {discardMessage,replacePhoto,generationParent} from './workflow';
import './goods.css';

export function GoodsWorkspace({userId}:{userId:string}){
 const [step,setStep]=useState(1),[style,setStyle]=useState<StyleId|null>(null),[work,setWork]=useState<string|null>(null),[source,setSource]=useState(''),[selected,setSelected]=useState<string|null>(null),[draft,setDraft]=useState(''),[rows,setRows]=useState<GoodsRevision[]>([]),[busy,setBusy]=useState(false),[error,setError]=useState(''),[saved,setSaved]=useState<GoodsDesign|null>(null),[preview,setPreview]=useState<{key:string;status:string}|null>(null),[placement,setPlacement]=useState<Placement>({holeX:.5,holeY:0,widthMm:50});
 const live=useRef(true),epoch=useRef(0),workRef=useRef<string|null>(null),sourceRef=useRef(''),savedRef=useRef(false),fileInput=useRef<HTMLInputElement>(null),pending=useRef<{body:string;key:string}|null>(null);
 const catalog=useQuery({queryKey:['goods-catalog',userId],queryFn:({signal})=>api<{styles:DesignStyle[]}>('/goods/catalog',{signal})});
 const current=rows.find(r=>r.id===selected),src=current?.image_url||source;
 const running=rows.some(r=>r.status==='queued'||r.status==='running');
 const uncertain=rows.some(r=>r.status==='unknown');
 const dirty=!saved&&(!!work||busy||!!draft||!!style);
 const blocker=useBlocker(dirty);
 function dispose(){epoch.current++;const id=workRef.current;workRef.current=null;if(id&&!savedRef.current)void abandon(id,true);}
 useEffect(()=>{
  live.current=true;
  return()=>{live.current=false;dispose();if(sourceRef.current)URL.revokeObjectURL(sourceRef.current);};
 },[]);
 useEffect(()=>{if(blocker.state==='blocked'){if(window.confirm(discardMessage)){dispose();blocker.proceed();}else blocker.reset();}},[blocker]);
 useEffect(()=>{
  if(!dirty)return;
  const before=(e:BeforeUnloadEvent)=>{e.preventDefault();e.returnValue='';};
  const logout=(e:Event)=>{if(!window.confirm(discardMessage))e.preventDefault();else dispose();};
  const hide=()=>dispose();
  const restore=(event:PageTransitionEvent)=>{if(event.persisted){setWork(null);setSource('');setRows([]);setSelected(null);setDraft('');setStyle(null);setStep(1);setBusy(false);setError('이전 작업은 화면을 떠나면서 폐기됐어요. 새로 시작해 주세요.');pending.current=null;}};
  window.addEventListener('pageshow',restore);
  window.addEventListener('beforeunload',before);window.addEventListener('pagehide',hide);window.addEventListener('mori:before-logout',logout);
  return()=>{window.removeEventListener('pageshow',restore);window.removeEventListener('beforeunload',before);window.removeEventListener('pagehide',hide);window.removeEventListener('mori:before-logout',logout);};
 },[dirty]);
 useEffect(()=>{
  if(!work||saved)return;let closed=false;let timer:number;
  const poll=async()=>{try{const data=await api<{revisions:GoodsRevision[]}>(`/goods/work/${work}`);if(!closed){const accepted=data.revisions.find(r=>r.request_key===pending.current?.key);if(accepted){pending.current=null;setSelected(accepted.id);setDraft('');}setRows(data.revisions);setSelected(old=>old??[...data.revisions].reverse().find(r=>r.status==='ready')?.id??null);}}catch(e){if(!closed)setError(errorText(e));}finally{if(!closed)timer=window.setTimeout(poll,2000);}};
  void poll();return()=>{closed=true;clearTimeout(timer);};
 },[work,saved]);
 async function upload(file?:File){
  if(!file||busy||running)return;
  setError('');setBusy(true);const token=epoch.current;
  let candidate:string|null=null;
  try{
   const id=await replacePhoto(!!work,()=>window.confirm('사진을 바꾸면 현재 사진과 생성한 시안, 대화 내역, 고리 위치 설정이 삭제됩니다. 새 사진으로 시작할까요?'),async()=>{
    if(!['image/png','image/jpeg','image/webp'].includes(file.type)||file.size>20*1024*1024)throw Error('20MB 이하 PNG·JPG·WebP 사진 1장을 선택해 주세요.');
    candidate=(await api<{id:string}>('/goods/work',{method:'POST',body:{},key:crypto.randomUUID()})).id;
    await uploadSource(candidate,file);
    if(!live.current||epoch.current!==token)throw Error('작업이 종료되었습니다.');
    return candidate;
   },async()=>{if(workRef.current)await abandon(workRef.current);});
   if(!id)return;
   if(!live.current||epoch.current!==token){void abandon(id);return;}
   workRef.current=id;setWork(id);candidate=null;
   if(sourceRef.current)URL.revokeObjectURL(sourceRef.current);
   sourceRef.current=URL.createObjectURL(file);setSource(sourceRef.current);setRows([]);setSelected(null);setDraft('');setPreview(null);setPlacement({holeX:.5,holeY:0,widthMm:50});pending.current=null;
  }catch(e){if(live.current&&epoch.current===token)setError(errorText(e));}
  finally{if(candidate)void abandon(candidate);if(live.current&&epoch.current===token)setBusy(false);}
 }
 async function generate(){
  if(!work||!style||!draft.trim()||busy||running||uncertain)return;
  const token=epoch.current;setBusy(true);setError('');
  const body={style,message:draft.trim(),parent_id:generationParent(rows,selected)};const serialized=JSON.stringify(body);
  if(pending.current&&pending.current.body!==serialized){setError('앞선 요청 결과를 확인한 뒤 내용을 바꿔 주세요.');setBusy(false);return;}
  pending.current??={body:serialized,key:crypto.randomUUID()};
  try{
   const result=await api<{id:string}>(`/goods/work/${work}/revisions`,{method:'POST',body,key:pending.current.key});
   if(!live.current||epoch.current!==token)return;
   pending.current=null;setDraft('');setSelected(result.id);
   const state=await api<{revisions:GoodsRevision[]}>(`/goods/work/${work}`);if(live.current&&epoch.current===token)setRows(state.revisions);
  }catch(e){if(live.current&&epoch.current===token)setError(errorText(e));}
  finally{if(live.current&&epoch.current===token)setBusy(false);}
 }
 async function finish(){
  if(!work||!current||busy)return;
  const token=epoch.current;setBusy(true);setError('');
  try{const result=await api<GoodsDesign>(`/goods/work/${work}/complete`,{method:'POST',body:{revision_id:current.id,placement}});if(!live.current||epoch.current!==token)return;savedRef.current=true;setSaved(result);}
  catch(e){if(live.current&&epoch.current===token)setError(errorText(e));}finally{if(live.current&&epoch.current===token)setBusy(false);}
 }
 const ready=!!current?.image_url&&current.status==='ready'&&preview?.status==='ready'&&preview.key===previewKey({src,product:'keyring',placement});
 if(saved)return <section className="goods-workspace"><ScreenHeader title="디자인이 완성됐어요" subtitle="내 디자인에 저장했어요. 사진첩은 이어서 연결할 수 있어요."/><>{saved.fake&&<p className="notice">개발용 가짜 AI 결과입니다.</p>}</><GoodsMockup src={saved.image_url} product="keyring" placement={saved.placement}/><Link className="button-link" to={`/designs/${saved.id}`}>앨범 연결하기</Link><Link className="button-link" to="/designs">내 디자인</Link></section>;
 return <section className="goods-workspace goods-designer">
  <div className="goods-step-label">0{step} / 03</div><ScreenHeader title={step===1?'모양을 골라 주세요':step===2?'시안을 함께 다듬어요':'고리를 달아 주세요'} subtitle="사진 한 장으로 만드는 나만의 작은 키링"/>
  {error&&<p role="alert">{error}</p>}{catalog.isError&&<button onClick={()=>void catalog.refetch()}>모양 목록 다시 불러오기</button>}
  {step===1&&<><StylePicker styles={catalog.data?.styles??[]} product="keyring" selected={style} disabled={busy||running} onSelect={setStyle}/><BottomActionBar><GlassButton disabled={!style} onClick={()=>setStep(2)}>이 모양으로 시작하기</GlassButton></BottomActionBar></>}
  {step===2&&<><div className="goods-editor-layout"><GlassPanel><h2>참고 사진 1장</h2>{src?<GoodsMockup src={src} product="keyring" placement={placement}/>:<p>기기에서 사진 한 장을 올려 주세요.</p>}<input hidden type="file" accept="image/png,image/jpeg,image/webp" ref={fileInput} onChange={e=>{const file=e.target.files?.[0];e.target.value='';void upload(file);}}/><GlassButton disabled={busy||running} onClick={()=>fileInput.current?.click()}>{busy?'처리 중…':work?'사진 바꾸기':'사진 업로드'}</GlassButton></GlassPanel><GlassPanel><h2>어떻게 만들어 볼까요?</h2><label htmlFor="goods-request">원하는 모습이나 수정할 내용</label><textarea id="goods-request" value={draft} maxLength={3000} disabled={busy||running} onChange={e=>setDraft(e.target.value)}/><GlassButton disabled={!work||!draft.trim()||busy||running||uncertain} onClick={()=>void generate()}>{running?'시안을 만들고 있어요…':pending.current?'같은 요청 다시 확인':'시안 생성·수정'}</GlassButton>{uncertain&&<p role="alert">AI 요청 결과를 확인하지 못했어요. 중복 호출을 막기 위해 자동 재시도하지 않습니다. 기존 시안은 보존돼 있어요.</p>}{current?.fake&&<p className="notice">개발용 가짜 AI 결과입니다.</p>}</GlassPanel></div>
   <RevisionHistory selectedId={selected} disabled={busy||running} onSelect={id=>{setSelected(id);setPreview(null);setPlacement({holeX:.5,holeY:0,widthMm:50});}} items={rows.map((r,i)=>r.status==='ready'?{id:r.id,label:`시안 ${i+1} · ${r.message}`,status:'ready',imageUrl:r.image_url!}:{id:r.id,label:`시안 ${i+1}`,status:r.status==='queued'||r.status==='running'?'pending':'failed'})}/>
   <BottomActionBar><GlassButton disabled={!current?.image_url||busy||running||uncertain} onClick={()=>setStep(3)}>이 시안으로 고리 위치 정하기</GlassButton></BottomActionBar><GlassButton variant="secondary" disabled={busy||running} onClick={()=>setStep(1)}>모양 선택으로</GlassButton></>}
  {step===3&&current?.image_url&&<><GoodsMockup src={src} product="keyring" placement={placement} interactive onChange={setPlacement} onPreview={setPreview}/><BottomActionBar><GlassButton disabled={!ready||busy} onClick={()=>void finish()}>{busy?'저장 중…':'디자인 완성하고 저장'}</GlassButton></BottomActionBar><GlassButton disabled={busy} variant="secondary" onClick={()=>setStep(2)}>시안으로 돌아가기</GlassButton></>}
 </section>;
}
