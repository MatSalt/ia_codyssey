import {PhotoFrame} from '../../components/media/PhotoFrame';
import {ViewerNavigation} from './ViewerNavigation';
import { useEffect, useRef, useState } from 'react';
import { Link, useParams } from 'react-router';
import { useQuery } from '@tanstack/react-query';
import { api, errorText } from '../../api/client';
import type { Viewer } from '../../api/types';
import { currentPageIndex, keyboardOffset, nextPageIndex, swipeOffset } from '../generation/flow';
import { DevAiNotice } from '../generation/DevAiNotice';
import { useSignedMedia } from './useSignedMedia';
import { SignedPhoto } from './SignedPhoto';
import { BackgroundMusic } from './BackgroundMusic';
const emptyAccess:Viewer['media_access']=[];
export function AlbumViewer({userId}:{userId:string}) {
 const {albumId=''}=useParams();const [currentId,setCurrentId]=useState<string|null>(null);const pointer=useRef<{x:number;y:number}|null>(null);
 const viewer=useQuery({queryKey:['viewer',userId,albumId],queryFn:({signal})=>api<Viewer>(`/albums/${albumId}/viewer`,{signal}),retry:false,refetchOnWindowFocus:false});
 const data=viewer.data;const pages=data?.pages??[];const index=currentPageIndex(pages,currentId);const page=pages[index];const next=pages[index+1];
 const media=useSignedMedia(albumId,pages.slice(index,index+2).map(p=>p.image.asset_id),data?.media_access??emptyAccess);
 useEffect(()=>{
  const key=(event:KeyboardEvent)=>{
   const editing=event.target instanceof HTMLElement && !!event.target.closest('input,textarea,select,[contenteditable="true"]');
   const offset=keyboardOffset(event.key,event.altKey||event.ctrlKey||event.metaKey||event.shiftKey,editing);
   if(event.defaultPrevented||!offset||!pages.length)return;event.preventDefault();
   setCurrentId(id=>pages[nextPageIndex(currentPageIndex(pages,id),offset,pages.length)].id);
  };window.addEventListener('keydown',key);return()=>window.removeEventListener('keydown',key);
 },[pages]);
 function turn(offset:number){const target=pages[nextPageIndex(index,offset,pages.length)];if(target)setCurrentId(target.id);}
 if(viewer.isPending)return <p role="status">사진첩을 펼치는 중…</p>;
 if(!data || !page)return <section><Link to="/albums">← 나의 책장</Link><p role="alert">{data?'감상할 사진이 없습니다.':errorText(viewer.error)}</p><p>완성된 사진첩만 감상할 수 있습니다.</p><Link to={`/albums/${albumId}/review`}>사진첩 결과 확인</Link><button className="secondary" onClick={()=>void viewer.refetch()}>다시 불러오기</button></section>;
 const access=media.access.find(a=>a.asset_id===page.image.asset_id);const adjacent=media.access.find(a=>a.asset_id===next?.image.asset_id);
 return <section className="album-viewer"><nav className="viewer-top" aria-label="사진첩 메뉴"><Link className="mori-icon-button" to="/albums" aria-label="책장으로">‹</Link><details className="viewer-options"><summary aria-label="사진첩 정보와 글귀 수정">···</summary><div><h1>{data.title}</h1><Link to={`/albums/${albumId}/review`}>글귀 수정</Link></div></details></nav><DevAiNotice mode={data.generation_mode}/><div className="viewer-frame"><div className="viewer-stage" tabIndex={0} aria-label={`${index+1}번째 사진. 좌우 방향키로 넘기기`} onPointerDown={event=>{if((event.target as HTMLElement).closest('button,a'))return;pointer.current={x:event.clientX,y:event.clientY};}} onPointerCancel={()=>{pointer.current=null;}} onPointerUp={event=>{
 const start=pointer.current;pointer.current=null;if(!start || (event.target as HTMLElement).closest('button,a'))return;
 const dx=event.clientX-start.x,dy=event.clientY-start.y;const offset=swipeOffset(dx,dy);
 if(offset){turn(offset);return;}if(Math.abs(dx)>10||Math.abs(dy)>10)return;
 const rect=event.currentTarget.getBoundingClientRect();const fraction=(event.clientX-rect.left)/rect.width;if(fraction<.2)turn(-1);else if(fraction>.8)turn(1);
 }}><PhotoFrame><SignedPhoto access={access} alt={`${index+1}번째 사진`} onFailure={media.failed} retry={()=>void media.refresh([page.image.asset_id])}/></PhotoFrame></div><BackgroundMusic key={albumId} music={data.music}/></div><p className="viewer-caption">{page.caption_text || <span className="sr-only">이 사진에는 글귀가 없습니다.</span>}</p><ViewerNavigation index={index} total={pages.length} onPrevious={()=>turn(-1)} onNext={()=>turn(1)}/>{adjacent && <img className="preload-image" src={adjacent.url} alt="" aria-hidden="true" onError={()=>media.failed(adjacent)}/>}{media.error && <div role="alert"><p>{media.error}</p><button className="secondary" disabled={media.renewing} onClick={()=>void media.refresh([page.image.asset_id,...(next?[next.image.asset_id]:[])])}>사진 주소 다시 받기</button></div>}<p className="hint viewer-hint">좌우로 밀거나 방향키로 넘길 수 있어요.</p></section>;
}
