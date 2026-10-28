import { useEffect, useRef } from 'react';
import { useBlocker } from 'react-router';
import { installUnsavedGuard } from './leaveGuard';
export function useUnsavedGuard(dirty:boolean,onDiscard:()=>void) {
 const blocker=useBlocker(dirty);const discard=useRef(onDiscard);discard.current=onDiscard;
 useEffect(()=>{
  if(blocker.state==='blocked'){
   if(window.confirm('저장하지 않은 글귀가 있습니다. 입력을 버리고 이동할까요?')){discard.current();blocker.proceed();}else blocker.reset();
  }
 },[blocker]);
 useEffect(()=>{
  if(!dirty)return;
  return installUnsavedGuard(window,()=>window.confirm('저장하지 않은 글귀를 버리고 로그아웃할까요?'));
 },[dirty]);
}
