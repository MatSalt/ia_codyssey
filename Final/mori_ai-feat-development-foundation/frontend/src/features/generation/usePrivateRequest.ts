import { useEffect, useRef } from 'react';
// Mutation requests have the same session lifetime as private query requests.
export function usePrivateRequest() {
 const current=useRef<AbortController>(new AbortController());
 useEffect(()=>{const controller=new AbortController();current.current=controller;const clear=()=>controller.abort();window.addEventListener('mori:logout',clear);window.addEventListener('mori:session-expired',clear);return()=>{clear();window.removeEventListener('mori:logout',clear);window.removeEventListener('mori:session-expired',clear);};},[]);
 return current;
}
