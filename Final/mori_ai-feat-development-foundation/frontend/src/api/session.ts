import {reviewDrafts} from '../features/review/drafts.js';
import {requestIntents} from '../features/generation/flow.js';
import type {QueryClient} from '@tanstack/react-query';
let owner:string|null=null;
function clearPrivateMemory() {
  requestIntents.clear();reviewDrafts.clear();
  if(typeof window!=='undefined')window.dispatchEvent(new Event('mori:clear-private-memory'));
}
export function selectSessionOwner(userId:string) {
  if(owner!==null && owner!==userId)clearPrivateMemory();
  owner=userId;reviewDrafts.selectOwner(userId);
}
export async function resetSession(cache:QueryClient,reason:'logout'|'expired'='logout'):Promise<void> {
  if(reason==='logout'){clearPrivateMemory();owner=null;}
  // Expiry removes private responses but preserves user-scoped unsent input and
  // exact mutation identities for a same-owner login. No input uses persistence.
  if(typeof window!=='undefined')window.dispatchEvent(new Event(reason==='logout'?'mori:logout':'mori:session-expired'));
  const isPublicConfig = (key: readonly unknown[]) => key[0] === 'dev-config' || (key.length === 1 && key[0] === 'client-config');
  await cache.cancelQueries({predicate:query=>!isPublicConfig(query.queryKey)});
  cache.removeQueries({predicate:query=>query.queryKey[0]!=='session' && !isPublicConfig(query.queryKey)});
  // Keep the mounted session observer attached with an explicit signed-out value.
  cache.setQueryData(['session'],null);
}
