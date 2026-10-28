import { api, ApiError } from '../../api/client.js';
import type { Detail } from '../../api/types';
export async function removeAlbum(albumId:string,signal:AbortSignal):Promise<void> {
 const latest=await api<Detail>(`/albums/${albumId}`,{signal});
 try {
  await api(`/albums/${albumId}?expected_version=${latest.detail.album.version}`,{method:'DELETE',signal});
 } catch(error) {
  const uncertain=error instanceof TypeError ||
   (error instanceof DOMException && error.name==='TimeoutError') ||
   (error instanceof ApiError && error.status>=500);
  if(!uncertain || signal.aborted)throw error;
  // A lost response does not prove failure. Confirm disappearance once without
  // repeating the mutation; version refusals and unknown confirmation stay errors.
  try { await api<Detail>(`/albums/${albumId}`,{signal}); }
  catch(confirmation) {
   if(confirmation instanceof ApiError && confirmation.status===404)return;
   throw error;
  }
  throw error;
 }
}
