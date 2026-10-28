// The router handles internal navigation; these events cover reload and logout.
export function installUnsavedGuard(target:EventTarget,confirmDiscard:()=>boolean):()=>void {
 const unload=(event:Event)=>{event.preventDefault();(event as BeforeUnloadEvent).returnValue='';};
 const logout=(event:Event)=>{if(!confirmDiscard())event.preventDefault();};
 target.addEventListener('beforeunload',unload);target.addEventListener('mori:before-logout',logout);
 return()=>{target.removeEventListener('beforeunload',unload);target.removeEventListener('mori:before-logout',logout);};
}
