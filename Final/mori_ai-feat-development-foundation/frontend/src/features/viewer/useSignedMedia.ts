import { useCallback, useEffect, useRef, useState } from 'react';
import { api, errorText } from '../../api/client';
import type { MediaAccess } from '../../api/types';
import { usePrivateRequest } from '../generation/usePrivateRequest';
import { useVisibility } from '../generation/useVisibility';
import { MediaRenewals } from '../generation/flow';
export function useSignedMedia(albumId:string,assetIds:string[],initial:MediaAccess[]) {
 const [access,setAccess]=useState(initial);const [error,setError]=useState('');const [renewing,setRenewing]=useState(false);
 const request=usePrivateRequest();const gate=useRef(new MediaRenewals());const latest=useRef({assetIds,access});latest.current={assetIds,access};const failedUrls=useRef(new Set<string>());
 const refresh=useCallback(async(forceIds?:string[])=>{
  if(request.current.signal.aborted)return;
  setRenewing(true);setError('');
  try{await gate.current.run(
   ()=>request.current.signal.aborted?[]:forceIds ?? latest.current.assetIds.filter(id=>!latest.current.access.some(a=>a.asset_id===id && Date.parse(a.expires_at)>Date.now()+10000)),
   ids=>api<{media_access:MediaAccess[]}>(`/albums/${albumId}/media-access`,{method:'POST',body:{asset_ids:ids},signal:request.current.signal}),
   result=>{if(!request.current.signal.aborted){
    const merged=[...latest.current.access.filter(a=>!result.media_access.some(n=>n.asset_id===a.asset_id)),...result.media_access];
    latest.current={...latest.current,access:merged};setAccess(merged);
   }});
  }catch(e){if(!request.current.signal.aborted)setError(errorText(e));}
  finally{if(!request.current.signal.aborted)setRenewing(gate.current.busy);}
 },[albumId,request]);
 const visible=useVisibility(()=>void refresh());
 const idsKey=assetIds.join(',');
 useEffect(()=>{const merged=[...latest.current.access.filter(a=>!initial.some(n=>n.asset_id===a.asset_id)),...initial];latest.current={...latest.current,access:merged};setAccess(merged);},[initial]);
 useEffect(()=>{if(visible)void refresh();},[idsKey,visible,refresh]);
 useEffect(()=>{
  if(!visible)return;
  const needed=access.filter(a=>assetIds.includes(a.asset_id));if(!needed.length)return;
  const expiry=Math.min(...needed.map(a=>Date.parse(a.expires_at)));
  const timer=window.setTimeout(()=>void refresh(),Math.max(1000,expiry-Date.now()-10000));return()=>window.clearTimeout(timer);
 },[idsKey,access,visible,refresh]);
 function failed(item:MediaAccess) {if(failedUrls.current.has(item.url))return;failedUrls.current.add(item.url);void refresh([item.asset_id]);}
 return {access,error,renewing,failed,refresh};
}
