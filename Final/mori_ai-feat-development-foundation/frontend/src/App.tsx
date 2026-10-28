import {workspaceKey} from './features/goods/workflow';
import {GoodsWorkspace} from './features/goods/GoodsWorkspace';
import {Designs,DesignDetail} from './features/goods/Designs';
import { Route, Routes, Navigate, Link, useParams, useLocation } from 'react-router';
import { useEffect, useState } from 'react';
import { AuthGate } from './features/auth/AuthGate';
import { Bookshelf } from './features/albums/Bookshelf';
import { AlbumEditor } from './features/albums/AlbumEditor';
import { GenerationProgress } from './features/generation/GenerationProgress';
import { ReviewEditor } from './features/review/ReviewEditor';
import { AlbumViewer } from './features/viewer/AlbumViewer';
import type { ComponentType } from 'react';
import { errorText } from './api/client';
import './styles.css';
function AlbumScreen({userId,Screen}:{userId:string;Screen:ComponentType<{userId:string}>}){const {albumId}=useParams();return <Screen key={`${userId}:${albumId}`} userId={userId}/>;}
function GoodsReturn({userId}:{userId:string}){
 const location=useLocation();const key=`mori:goods-return:${userId}`;
 const [target,setTarget]=useState<string|null>(()=>sessionStorage.getItem(key));
 useEffect(()=>{const id=new URLSearchParams(location.search).get('connect_design');if(id&&/^[0-9a-f-]{36}$/.test(id)){sessionStorage.setItem(key,id);setTarget(id);}if(location.pathname.startsWith('/designs')){sessionStorage.removeItem(key);setTarget(null);}},[location.pathname,location.search,key]);
 return target&&location.pathname.startsWith('/albums')?<p className="goods-return"><Link to={`/designs/${target}`}>앨범 완성 후 디자인으로 돌아가 연결하기</Link></p>:null;
}
export default function App() {
 const location=useLocation();
 const [error,setError] = useState('');
 return <><a className="skip-link" href="#main-content">본문으로 건너뛰기</a><main id="main-content" tabIndex={-1}><AuthGate>{(me,logout) => <><details className="app-account"><summary aria-label={`${me.user.display_name} 계정 메뉴`}>{me.user.display_name.slice(0,1)}</summary><div><p>{me.user.display_name}님의 공간</p><nav aria-label="내 프로필 메뉴"><Link to="/goods">굿즈 만들기</Link><Link to="/designs">내 디자인</Link><Link to="/albums">내 책장</Link></nav><button className="text" onClick={() => {if(window.dispatchEvent(new Event('mori:before-logout',{cancelable:true})))void logout().catch(e => setError(errorText(e)));}}>로그아웃</button></div></details>{error && <p role="alert">{error}</p>}<GoodsReturn key={me.user.id} userId={me.user.id}/><Routes><Route path="/goods" element={<GoodsWorkspace key={workspaceKey(me.user.id,location.key)} userId={me.user.id}/>}/><Route path="/designs" element={<Designs userId={me.user.id}/>}/><Route path="/designs/:designId" element={<DesignDetail key={me.user.id} userId={me.user.id}/>}/><Route path="/albums" element={<Bookshelf userId={me.user.id}/>}/><Route path="/albums/:albumId/edit" element={<AlbumScreen Screen={AlbumEditor} userId={me.user.id}/>}/><Route path="/albums/:albumId/progress" element={<AlbumScreen Screen={GenerationProgress} userId={me.user.id}/>}/><Route path="/albums/:albumId/review" element={<AlbumScreen Screen={ReviewEditor} userId={me.user.id}/>}/><Route path="/albums/:albumId/view" element={<AlbumScreen Screen={AlbumViewer} userId={me.user.id}/>}/><Route path="*" element={<Navigate to="/goods" replace/>}/></Routes></>}</AuthGate></main></>;
}
