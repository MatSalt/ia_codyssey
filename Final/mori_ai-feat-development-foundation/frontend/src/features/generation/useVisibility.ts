import { useEffect, useState, useRef } from 'react';
export function useVisibility(refresh:()=>unknown) {
 const [visible,setVisible]=useState(!document.hidden);const latest=useRef(refresh);latest.current=refresh;
 useEffect(()=>{const change=()=>{setVisible(!document.hidden);if(!document.hidden)latest.current();};document.addEventListener('visibilitychange',change);return()=>document.removeEventListener('visibilitychange',change);},[]);
 return visible;
}
