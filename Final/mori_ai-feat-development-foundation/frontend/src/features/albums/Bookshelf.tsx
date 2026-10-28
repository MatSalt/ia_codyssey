import {GlassButton} from '../../components/ui/GlassButton';
import {AlbumCard} from './AlbumCard';
import {ScreenHeader} from '../../components/layout/ScreenHeader';
import {BottomActionBar} from '../../components/layout/BottomActionBar';
import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router';
import { useInfiniteQuery, useQueryClient } from '@tanstack/react-query';
import { api, errorText } from '../../api/client';
import type { Album, MediaAccess } from '../../api/types';
import { albumPath } from '../generation/flow';
import { usePrivateRequest } from '../generation/usePrivateRequest';
import { removeAlbum } from './removeAlbum';
const albumLabels:Record<string,string>={draft:'초안',processing:'생성 중',action_required:'확인 필요',review_ready:'결과 확인',published:'완성'};
const createKeys = new Map<string,string>();
window.addEventListener('mori:logout',()=>createKeys.clear());
window.addEventListener('mori:clear-private-memory',()=>createKeys.clear());
function Cover({album,access,renew}:{album:Album;access?:MediaAccess;renew:()=>void}) {
 const [failed,setFailed]=useState(false);
 useEffect(()=>setFailed(false),[access?.url]);
 useEffect(()=>{if(!access)return;const timer=window.setTimeout(renew,Math.max(1000,Date.parse(access.expires_at)-Date.now()-10000));return()=>window.clearTimeout(timer);},[access?.url]);
 return <div className="cover">{access && !failed ? <img src={access.url} alt={`${album.title} 표지`} onError={()=>{setFailed(true);renew();}}/> : <><span aria-hidden="true">▤</span><span>{album.page_count}장의 기억</span></>}</div>;
}
export function Bookshelf({userId}: {userId:string}) {
 const [deletingId,setDeletingId]=useState<string|null>(null);const cache=useQueryClient();
 const request=usePrivateRequest();const navigate = useNavigate(); const key = useRef<string|null>(createKeys.get(userId) ?? null); const [busy,setBusy] = useState(false); const [error,setError] = useState('');
 const albums = useInfiniteQuery({queryKey:['albums',userId],initialPageParam:'',queryFn:({pageParam,signal}) => api<{items:Album[];next_cursor:string|null;media_access:MediaAccess[]}>(`/albums${pageParam ? `?cursor=${encodeURIComponent(pageParam)}` : ''}`,{signal}),getNextPageParam:last => last.next_cursor ?? undefined});
 async function create() { if(busy)return; setBusy(true); setError(''); key.current ??= crypto.randomUUID(); createKeys.set(userId,key.current); try {const result = await api<{album:Album}>('/albums',{method:'POST',body:{},key:key.current,signal:request.current.signal}); if(request.current.signal.aborted)return;key.current=null; createKeys.delete(userId); navigate(`/albums/${result.album.id}/edit`);}catch(e){if(!request.current.signal.aborted)setError(errorText(e));}finally{if(!request.current.signal.aborted)setBusy(false);} }
 async function remove(album:Album){
  if(busy||deletingId||!window.confirm(`${album.title} 사진첩과 모든 사진을 삭제할까요?`))return;setDeletingId(album.id);setError('');
  try{await removeAlbum(album.id,request.current.signal);if(!request.current.signal.aborted)await cache.invalidateQueries({queryKey:['albums',userId]});}
  catch(e){if(!request.current.signal.aborted){setError(errorText(e));await albums.refetch();}}finally{if(!request.current.signal.aborted)setDeletingId(null);}
 }
 const items = albums.data?.pages.flatMap(p=>p.items) ?? [];
 return <section className="bookshelf-screen"><ScreenHeader title="내 책장" subtitle="다시 펼쳐보고 싶은 순간들"/>{error && <p role="alert">{error}{key.current?' 같은 생성 요청으로 다시 시도합니다.':''}</p>}{albums.isPending && <p role="status">책장을 불러오고 있어요…</p>}{albums.isError && <div role="alert"><p>{errorText(albums.error)}</p><button onClick={()=>void albums.refetch()}>책장 다시 불러오기</button></div>}{!albums.isPending && !albums.isError && !items.length && <div className="empty"><div className="memory-cards" aria-hidden="true"><span/><span/></div><h2>아직은 비어 있는 책장</h2><p>새 사진첩을 만들고 좋아하는 사진을 담아 보세요.</p></div>}<div className="books">{items.map(album=><AlbumCard key={album.id} title={album.title} meta={`${new Date(album.updated_at).toLocaleDateString('ko-KR')} · 사진 ${album.page_count}장`} destination={albumPath(album)} cover={<Cover album={album} access={albums.data?.pages.flatMap(p=>p.media_access).find(a=>a.asset_id===album.cover?.asset_id)} renew={()=>void albums.refetch()}/>} status={album.status==='published'?undefined:albumLabels[album.status]??album.status} menu={<details className="book-options"><summary aria-label={`${album.title} 사진첩 더보기`}>···</summary><button className="text danger" disabled={busy||!!deletingId} aria-label={`${album.title} 사진첩 삭제`} onClick={()=>void remove(album)}>{deletingId===album.id?'삭제 중…':'사진첩 삭제'}</button></details>}/>)}</div>{albums.hasNextPage && <button className="secondary" disabled={albums.isFetchingNextPage} onClick={()=>void albums.fetchNextPage()}>사진첩 더 보기</button>}<BottomActionBar><GlassButton disabled={busy||!!deletingId} onClick={() => void create()}>{busy?'사진첩 준비 중…':key.current?'사진첩 생성 다시 시도':'+ 새 사진첩'}</GlassButton></BottomActionBar></section>;
}
