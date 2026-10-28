import {api,uploadHeaders,ApiError} from '../../api/client';
import type {Placement} from './mockup/preview';
export interface GoodsRevision {id:string;request_key:string;parent_id:string|null;message:string;style:string;status:'queued'|'running'|'ready'|'failed'|'unknown'|'cancelled';image_url:string|null;error_code:string|null;fake:boolean}
export interface GoodsDesign {id:string;fake:boolean;image_url:string;placement:Placement;album_id:string|null;version:number;production_started:boolean;created_at:string}
export async function uploadSource(work:string,file:File){
 const url=`/api/v1/goods/work/${work}/source`;
 const response=await fetch(url,{method:'PUT',body:file,credentials:'same-origin',headers:uploadHeaders(url,{'Content-Type':file.type}),signal:AbortSignal.timeout(60000)});
 if(!response.ok)throw new ApiError(response.status,'UPLOAD_FAILED','사진을 확인하지 못했어요. 파일 형식·크기를 확인해 주세요.');
}
export function abandon(work:string,keepalive=false){
 const url=`/api/v1/goods/work/${work}`;
 return fetch(url,{method:'DELETE',credentials:'same-origin',headers:uploadHeaders(url,{}),keepalive}).catch(()=>undefined);
}
export const goodsApi=api;
