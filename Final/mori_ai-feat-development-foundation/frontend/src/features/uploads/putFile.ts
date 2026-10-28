// Cache only by File identity: a retry must verify the exact original selection.
const hashes = new WeakMap<File, Promise<string>>();
function conditional(headers: Record<string,string>) {
 return Object.entries(headers).some(([key,value])=>key.toLowerCase()==='if-none-match' && value==='*');
}
export async function completionBody(file:File, headers:Record<string,string>):Promise<{sha256?:string}> {
 if(!conditional(headers))return {};
 if(file.size>20971520)throw new Error('파일은 20MiB 이하여야 합니다.');
 if(!globalThis.crypto?.subtle)throw new Error('SHA256 검증을 사용할 수 없습니다. 안전한 연결에서 다시 시도해 주세요.');
 let hash=hashes.get(file);
 if(!hash) {
  hash=file.arrayBuffer().then(bytes=>crypto.subtle.digest('SHA-256',bytes)).then(bytes=>Array.from(new Uint8Array(bytes),b=>b.toString(16).padStart(2,'0')).join(''));
  hashes.set(file,hash);
  hash.catch(()=>hashes.delete(file));
 }
 return {sha256:await hash};
}
export async function putFile(url:string,file:File,headers:Record<string,string>,signal:AbortSignal):Promise<'uploaded'|'verify'> {
 signal.throwIfAborted();
 let response:Response;
 try {
  response=await fetch(url,{method:'PUT',headers,body:file,credentials:'same-origin',signal:AbortSignal.any([signal,AbortSignal.timeout(120000)])});
 } catch(error) {
  signal.throwIfAborted();
  // CORS can hide a conditional collision, and a timeout can lose a stored PUT response.
  if(conditional(headers) && (error instanceof TypeError || (error instanceof Error && error.name==='TimeoutError')))return 'verify';
  throw error;
 }
 signal.throwIfAborted();
 if(response.status===412 && conditional(headers))return 'verify';
 if(!response.ok)throw new Error(`파일 전송 실패 (${response.status}). 같은 요청으로 다시 시도해 주세요.`);
 return 'uploaded';
}

interface UploadTarget { upload_id:string; upload_url:string; required_headers:Record<string,string> }
interface UploadProgress { put:Set<string>; complete:Set<string> }
// The hook and tests share the actual transfer/completion transition, including retry markers.
export async function uploadStep(
 upload:UploadTarget,file:File,progress:UploadProgress,signal:AbortSignal,putHeaders:Record<string,string>,
 status:()=>Promise<{status:string}>,complete:(body:{sha256?:string})=>Promise<unknown>,
):Promise<void> {
 signal.throwIfAborted();
 if(progress.complete.has(upload.upload_id))return;
 const remote=conditional(upload.required_headers);
 try {
  const body=await completionBody(file,upload.required_headers);
  signal.throwIfAborted();
  if(!progress.put.has(upload.upload_id)) {
   const state=await status();
   signal.throwIfAborted();
   if(state.status==='reserved')await putFile(upload.upload_url,file,putHeaders,signal);
   if(!remote)progress.put.add(upload.upload_id);
  }
  signal.throwIfAborted();
  await complete(body);
  signal.throwIfAborted();
  progress.put.add(upload.upload_id);
  progress.complete.add(upload.upload_id);
 } catch(error) {
  // No R2 marker survives an inconclusive completion; the same reservation may need PUT again.
  if(remote)progress.put.delete(upload.upload_id);
  throw error;
 }
}
