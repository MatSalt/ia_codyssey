import {useEffect,useRef,useState} from 'react';
import {GlassButton} from '../../../components/ui/GlassButton';
import {GlassPanel} from '../../../components/ui/GlassPanel';
import {IconButton} from '../../../components/ui/IconButton';
import {ScreenHeader} from '../../../components/layout/ScreenHeader';
import {BottomActionBar} from '../../../components/layout/BottomActionBar';
import {GoodsMockup} from '../mockup/GoodsMockup';
import {previewKey} from '../mockup/preview';
import type {Placement,PreviewInput} from '../mockup/preview';
import {StylePicker} from './StylePicker';
import type {DesignStyle,StyleId} from './catalog';

type Message={role:'user'|'assistant';text:string};
type ChatRequest={style:StyleId;artworkUrl:string;message:string;history:Message[]};
export function GoodsDesigner({styles,onChat}:{styles:DesignStyle[];onChat?:(request:ChatRequest)=>Promise<{text:string;artworkUrl?:string}>}){
 const [step,setStep]=useState<1|2|3>(1),[style,setStyle]=useState<StyleId|null>(null),[src,setSrc]=useState('');
 const [placement,setPlacement]=useState<Placement>({holeX:.5,holeY:0,widthMm:50});
 const [preview,setPreview]=useState<{key:string;status:string}|null>(null);
 const [messages,setMessages]=useState<Message[]>([]),[draft,setDraft]=useState(''),[busy,setBusy]=useState(false),[reading,setReading]=useState(false),[error,setError]=useState(''),[complete,setComplete]=useState(false);
 const fileInput=useRef<HTMLInputElement>(null),ownedUrl=useRef(''),selection=useRef(0),alive=useRef(true);
 useEffect(()=>{alive.current=true;return()=>{alive.current=false;selection.current++;if(ownedUrl.current)URL.revokeObjectURL(ownedUrl.current);};},[]);
 const input:PreviewInput|null=src?{src,product:'keyring',placement}:null;
 const ready=!!input&&!reading&&preview?.status==='ready'&&preview.key===previewKey(input);
 const styleName=styles.find(row=>row.id===style)?.label||'';
 function changeStep(next:1|2|3){setStep(next);setError('');setComplete(false);window.scrollTo({top:0,behavior:'instant'});}
 async function upload(file:File|undefined){
  if(!file)return;const current=++selection.current;setError('');setReading(true);setComplete(false);
  let candidate='';
  try{
   if(!['image/png','image/jpeg','image/webp'].includes(file.type)||file.size>20*1024*1024)throw new Error('20MB 이하의 PNG, JPG, WebP 시안을 선택해 주세요.');
   candidate=URL.createObjectURL(file);const image=new Image();
   await new Promise<void>((resolve,reject)=>{image.onload=()=>resolve();image.onerror=()=>reject(new Error('이미지를 읽지 못했어요. 다른 시안을 선택해 주세요.'));image.src=candidate;});
   if(image.naturalWidth*image.naturalHeight>16_000_000)throw new Error('1600만 화소 이하의 시안을 선택해 주세요.');
   if(current!==selection.current||!alive.current)return;
   if(ownedUrl.current)URL.revokeObjectURL(ownedUrl.current);ownedUrl.current=candidate;candidate='';
   setSrc(ownedUrl.current);setPreview(null);setPlacement({holeX:.5,holeY:0,widthMm:50});setMessages([]);
  }catch(e){if(current===selection.current&&alive.current)setError(e instanceof Error?e.message:'시안을 읽지 못했어요.');}
  finally{if(candidate)URL.revokeObjectURL(candidate);if(current===selection.current&&alive.current)setReading(false);}
 }
 async function send(){
  if(!onChat||!style||!src||!draft.trim()||busy||reading)return;
  const text=draft.trim(),current=selection.current;setBusy(true);setError('');
  try{const reply=await onChat({style,artworkUrl:src,message:text,history:messages});if(!alive.current||current!==selection.current)return;
   setMessages(rows=>[...rows,{role:'user',text},{role:'assistant',text:reply.text}]);setDraft('');
   if(reply.artworkUrl){setSrc(reply.artworkUrl);setPreview(null);setComplete(false);}
  }catch{if(alive.current)setError('답변을 받지 못했어요. 입력한 내용은 남겨 두었어요.');}
  finally{if(alive.current)setBusy(false);}
 }
 return <main className="goods-workspace goods-designer">
  <div className="goods-step-label" aria-label={`3단계 중 ${step}단계`}><span>{String(step).padStart(2,'0')}</span> / 03 <span>{['모양 선택','시안 만들기','고리 위치'][step-1]}</span></div>
  <ScreenHeader title={['모양을 골라 주세요','시안을 함께 다듬어요','고리를 달아 주세요'][step-1]} subtitle={step===1?'사진을 닮은, 나만의 작은 키링':step===2?`${styleName} · 시안을 올리고 미리 확인해 보세요`:'원하는 테두리를 가볍게 눌러 주세요'} leading={step>1?<IconButton label="이전 단계" disabled={busy||reading} onClick={()=>changeStep(step===3?2:1)}>‹</IconButton>:undefined}/>
  {step===1&&<><StylePicker styles={styles} product="keyring" selected={style} onSelect={id=>{if(id!==style){setStyle(id);setMessages([]);}}}/><BottomActionBar><GlassButton disabled={!style} onClick={()=>changeStep(2)}>{style?`${styleName}로 시작하기`:'모양을 선택해 주세요'}</GlassButton></BottomActionBar></>}
  {step===2&&<>
   <div className="goods-editor-layout"><section className="goods-artwork-section"><GlassPanel className="goods-mockup-panel">
    {input?<GoodsMockup {...input} onPreview={setPreview}/>:<div className="goods-upload-empty"><span aria-hidden="true">＋</span><h2>시안을 올려 주세요</h2><p>그림이나 사진을 올리면<br/>키링 모습을 미리 볼 수 있어요.</p></div>}
    <GlassButton variant="secondary" className="goods-upload-button" disabled={busy||reading} onClick={()=>fileInput.current?.click()}>{reading?'시안을 읽고 있어요…':src?'시안 바꾸기':'시안 업로드'}</GlassButton>
    <input ref={fileInput} type="file" aria-label="시안 이미지 선택" hidden accept="image/png,image/jpeg,image/webp" onChange={event=>{const file=event.target.files?.[0];event.target.value='';void upload(file);}}/>
    <p className="goods-note">PNG · JPG · WebP / 투명 배경 PNG를 권장해요.</p>
   </GlassPanel></section>
   <GlassPanel className="goods-chat"><h2>어떻게 바꿔 볼까요?</h2><div className="goods-chat-messages" role="log" aria-label="디자인 대화">{messages.length?messages.map((m,i)=><p key={i} className={`goods-message goods-message--${m.role}`}><span>{m.role==='user'?'나':'mori'}</span>{m.text}</p>):<p className="goods-chat-welcome">원하는 색이나 문구,<br/>바꾸고 싶은 부분을 적어 주세요.</p>}</div>
    <form onSubmit={event=>{event.preventDefault();void send();}}><label className="goods-chat-label" htmlFor="goods-message">수정 요청</label><textarea id="goods-message" rows={3} maxLength={3000} value={draft} disabled={busy} placeholder="예: 글자를 ‘우리의 여름’으로 바꿔 줘" onChange={e=>setDraft(e.target.value)}/><GlassButton type="submit" disabled={!onChat||!src||!draft.trim()||busy||reading}>{busy?'답변을 기다리고 있어요…':'보내기'}</GlassButton></form>
    {!onChat&&<p className="goods-note">AI 대화는 준비 중이에요. 지금은 시안을 올려 미리 볼 수 있어요.</p>}
   </GlassPanel></div>
   <BottomActionBar><GlassButton disabled={!ready||busy} onClick={()=>changeStep(3)}>이 시안으로 고리 위치 정하기 <span aria-hidden="true">→</span></GlassButton></BottomActionBar>
  </>}
  {step===3&&input&&<><GlassPanel className="goods-mockup-panel goods-placement"><GoodsMockup {...input} interactive onChange={value=>{setPlacement(value);setComplete(false);}} onPreview={setPreview}/></GlassPanel><BottomActionBar><GlassButton disabled={!ready} onClick={()=>setComplete(true)}>이 위치로 선택 완료</GlassButton></BottomActionBar>{complete&&<p role="status" className="goods-complete">고리 위치를 선택했어요.</p>}</>}
  {error&&<p role="alert" className="goods-error">{error}</p>}
 </main>;
}
