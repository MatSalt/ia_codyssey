import { useEffect, useState } from 'react';
import type { MediaAccess } from '../../api/types';
export function SignedPhoto({access,alt,onFailure,retry}:{access?:MediaAccess;alt:string;onFailure:(access:MediaAccess)=>void;retry:()=>void}) {
 const [failed,setFailed]=useState(false);
 useEffect(()=>setFailed(false),[access?.url]);
 return access && !failed ? <img src={access.url} alt={alt} draggable={false} onError={()=>{setFailed(true);onFailure(access);}}/> : <div className="placeholder"><span aria-hidden="true">▧</span><p role="status">{failed?'사진을 불러오지 못했어요.':'사진을 준비하고 있어요…'}</p><button className="secondary" onClick={()=>{setFailed(false);retry();}}>사진 다시 불러오기</button></div>;
}
