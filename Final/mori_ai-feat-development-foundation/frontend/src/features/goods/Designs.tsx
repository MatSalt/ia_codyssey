import {useRef,useState} from 'react';
import {Link,useNavigate,useParams} from 'react-router';
import {useInfiniteQuery,useQuery,useQueryClient} from '@tanstack/react-query';
import {api,errorText} from '../../api/client';
import type {Album} from '../../api/types';
import type {GoodsDesign} from './api';
import {GoodsMockup} from './mockup/GoodsMockup';
import {GlassButton} from '../../components/ui/GlassButton';
import {ScreenHeader} from '../../components/layout/ScreenHeader';
import {PhotoFrame} from '../../components/media/PhotoFrame';
import './goods.css';
export function Designs({userId}:{userId:string}){
 const query=useInfiniteQuery({queryKey:['goods-designs',userId],initialPageParam:0,queryFn:({pageParam,signal})=>api<{items:GoodsDesign[];next_offset:number|null}>(`/goods/designs?offset=${pageParam}`,{signal}),getNextPageParam:last=>last.next_offset??undefined});
 return <section className="bookshelf-screen"><ScreenHeader title="내 디자인" subtitle="완성한 나만의 굿즈"/>{query.isPending&&<p role="status">불러오고 있어요…</p>}{query.isError&&<p role="alert">{errorText(query.error)} <button onClick={()=>void query.refetch()}>다시 불러오기</button></p>}{query.data?.pages[0].items.length===0&&<p>아직 완성한 디자인이 없어요.</p>}<div className="books">{query.data?.pages.flatMap(p=>p.items).map(d=><Link key={d.id} to={`/designs/${d.id}`}><PhotoFrame ratio="square"><img src={d.image_url} alt="완성한 굿즈 디자인"/></PhotoFrame><p>{d.fake?'가짜 AI · ':''}{new Date(d.created_at).toLocaleDateString('ko-KR')} · {d.album_id?'앨범 연결됨':'앨범 연결하기'}</p></Link>)}</div>{query.hasNextPage&&<GlassButton disabled={query.isFetchingNextPage} onClick={()=>void query.fetchNextPage()}>더 보기</GlassButton>}<Link className="button-link" to="/goods">굿즈 만들기</Link></section>;
}
export function DesignDetail({userId}:{userId:string}){
 const {designId}=useParams();const navigate=useNavigate(),cache=useQueryClient();
 const [error,setError]=useState(''),[busy,setBusy]=useState(false);const createKey=useRef<string|null>(null);
 const detail=useQuery({queryKey:['goods-design',userId,designId],queryFn:({signal})=>api<GoodsDesign>(`/goods/designs/${designId}`,{signal})});
 const albums=useInfiniteQuery({queryKey:['goods-albums',userId],initialPageParam:'',queryFn:({pageParam,signal})=>api<{items:Album[];next_cursor:string|null}>(`/albums${pageParam?`?cursor=${encodeURIComponent(pageParam)}`:''}`,{signal}),getNextPageParam:last=>last.next_cursor??undefined});
 async function connect(albumId:string){if(!detail.data||busy)return;setBusy(true);setError('');try{await api(`/goods/designs/${designId}/album`,{method:'PUT',body:{album_id:albumId,expected_version:detail.data.version}});await cache.invalidateQueries({queryKey:['goods-design',userId,designId]});await cache.invalidateQueries({queryKey:['goods-designs',userId]});}catch(e){setError(errorText(e));void detail.refetch();}finally{setBusy(false);}}
 async function create(){if(busy)return;setBusy(true);setError('');createKey.current??=crypto.randomUUID();try{const data=await api<{album:Album}>('/albums',{method:'POST',body:{},key:createKey.current});createKey.current=null;navigate(`/albums/${data.album.id}/edit?connect_design=${designId}`);}catch(e){setError(errorText(e));}finally{setBusy(false);}}
 const d=detail.data;
 return <section className="goods-workspace"><ScreenHeader title="내 디자인" subtitle="앨범 연결은 디자인 완성과 별도로 할 수 있어요."/>{detail.isError&&<p role="alert">{errorText(detail.error)} <button onClick={()=>void detail.refetch()}>다시 불러오기</button></p>}{error&&<p role="alert">{error}</p>}{!d&&!detail.isError&&<p>불러오고 있어요…</p>}{d&&<>{d.fake&&<p className="notice">개발용 가짜 AI 결과입니다.</p>}<GoodsMockup src={d.image_url} product="keyring" placement={d.placement}/><h2>앨범 연결하기</h2>{d.album_id&&<Link to={`/albums/${d.album_id}/view`}>연결된 앨범 보기</Link>}{d.production_started?<p>제작 요청이 시작되어 연결 앨범을 바꿀 수 없어요.</p>:<><p>기존에 완성한 앨범을 선택하거나 새로 만들어 주세요. 새 앨범을 완성한 뒤 이 화면으로 돌아와 연결할 수 있어요.</p>{albums.isError&&<button onClick={()=>void albums.refetch()}>앨범 목록 다시 불러오기</button>}<div className="stack">{albums.data?.pages.flatMap(p=>p.items).filter(a=>a.status==='published').map(a=><GlassButton variant="secondary" key={a.id} disabled={busy||a.id===d.album_id} onClick={()=>void connect(a.id)}>{a.title} · {a.page_count}장 {a.id===d.album_id?'(연결됨)':''}</GlassButton>)}</div>{albums.hasNextPage&&<GlassButton variant="secondary" disabled={albums.isFetchingNextPage} onClick={()=>void albums.fetchNextPage()}>앨범 더 보기</GlassButton>}<GlassButton disabled={busy} onClick={()=>void create()}>새 앨범 만들기</GlassButton></>}</>}<p><Link to="/designs">내 디자인 목록</Link></p></section>;
}
