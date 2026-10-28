import { useEffect, useRef, useState } from 'react';
import { api, ApiError, errorText, uploadHeaders } from '../../api/client';
import { uploadStep } from './putFile';
import { prepareFiles } from './preprocess';
import type { Detail, Reservation, UploadView } from '../../api/types';
interface Intent { key:string; files:{file:File;id:string}[]; body:unknown; reservation?:Reservation; put:Set<string>; complete:Set<string> }
const drafts = new Map<string,{files:File[];intent:Intent|null}>();
window.addEventListener('mori:logout',()=>drafts.clear());
window.addEventListener('mori:clear-private-memory',()=>drafts.clear());
export function useUploads(albumId:string, userId:string, refresh:()=>Promise<unknown>) {
 const draftKey=`${userId}:${albumId}`;
 const intent = useRef<Intent|null>(drafts.get(draftKey)?.intent ?? null); const controller = useRef<AbortController|null>(null);
 const [files,setFiles] = useState<File[]>(drafts.get(draftKey)?.files ?? []); const [busy,setBusy] = useState(false); const [error,setError] = useState(''); const [progress,setProgress] = useState('');
 const latestFiles=useRef(files); latestFiles.current=files;
 useEffect(()=>{
  let discard=false;
  const clear=()=>{discard=true;drafts.clear();intent.current=null;controller.current?.abort();latestFiles.current=[];setFiles([]);};
  const expire=()=>controller.current?.abort();
  window.addEventListener('mori:logout',clear);window.addEventListener('mori:clear-private-memory',clear);window.addEventListener('mori:session-expired',expire);
  return()=>{controller.current?.abort();controller.current=null;if(!discard)drafts.set(draftKey,{files:latestFiles.current,intent:intent.current});window.removeEventListener('mori:logout',clear);window.removeEventListener('mori:clear-private-memory',clear);window.removeEventListener('mori:session-expired',expire);};
 },[draftKey]);
 async function send() {
  if(busy || !files.length)return;
  setBusy(true); setError(''); const abort = new AbortController(); controller.current=abort;
  try {
   if (!intent.current) {
    const prepared=await prepareFiles(files,abort.signal,name=>setProgress(`${name} · 사진 준비 중`));
    const selected=prepared.map(item=>({...item,id:crypto.randomUUID()}));
    const latest=await api<Detail>(`/albums/${albumId}`,{signal:abort.signal});
    abort.signal.throwIfAborted();
    intent.current={key:crypto.randomUUID(),files:selected,body:{expected_version:latest.detail.album.version,files:selected.map(({file,id,preprocessing})=>({client_file_id:id,filename:file.name,mime:file.type,bytes:file.size,file_last_modified_at:new Date(file.lastModified).toISOString(),...(preprocessing?{preprocessing}:{})}))},put:new Set(),complete:new Set()};
   }
   const current=intent.current;
   setProgress('업로드 공간 예약 중');
   current.reservation ??= await api<Reservation>(`/albums/${albumId}/uploads`,{method:'POST',body:current.body,key:current.key,signal:abort.signal});
   for (const upload of current.reservation.uploads) {
    const file=current.files.find(f=>f.id===upload.client_file_id)!.file;
    setProgress(`${file.name} · 업로드 중`);
    await uploadStep(upload,file,current,abort.signal,uploadHeaders(upload.upload_url,upload.required_headers),
     ()=>api<UploadView>(`/albums/${albumId}/uploads/${upload.upload_id}`,{signal:abort.signal}),
     body=>{setProgress(`${file.name} · 전송 확인 중 (연결 상태에 따라 최대 3분)`);return api<UploadView>(`/albums/${albumId}/uploads/${upload.upload_id}/complete`,{method:'POST',body,signal:abort.signal});});
   }
   await refresh(); intent.current=null; setFiles([]); setProgress('전송 완료 · 서버에서 사진을 검증하고 정규화합니다.');
  }catch(e){if(!abort.signal.aborted){if(e instanceof ApiError && e.status!==401 && e.status<500 && !intent.current?.reservation)intent.current=null;setError(errorText(e)); await refresh().catch(()=>undefined);}}finally{if(controller.current===abort){controller.current=null;setBusy(false);}}
 }
 function select(next:File[]) { if(intent.current || busy)return; setFiles(next); setError(''); setProgress(''); }
 function discard() { intent.current=null; setFiles([]); setError(''); setProgress(''); }
 return {files,select,send,busy,error,progress,locked:intent.current!==null,discard};
}
