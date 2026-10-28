export interface MusicState { playing:boolean; pending:boolean; error:boolean }

// Own the audio lifecycle independently of the viewer's layout and page turns.
export function createMusicPlayback(audio:HTMLAudioElement, url:string, visibility:Pick<Document,'hidden'|'addEventListener'|'removeEventListener'>, events:EventTarget, changed:(state:MusicState)=>void) {
 let state:MusicState={playing:false,pending:false,error:false};
 let disposed=false, wanted=false, revision=0;
 const update=(patch:Partial<MusicState>)=>{state={...state,...patch};if(!disposed)changed({...state});};
 audio.src=url;audio.loop=true;audio.preload='none';audio.volume=.35;
 function stop(){wanted=false;revision++;audio.pause();update({playing:false,pending:false});}
 const hidden=()=>{if(visibility.hidden)stop();};
 const failed=()=>{stop();update({error:true});};
 const paused=()=>{wanted=false;revision++;update({playing:false,pending:false});};
 const stopEvents=['pagehide','mori:session-expired','mori:logout'];
 visibility.addEventListener('visibilitychange',hidden);
 stopEvents.forEach(name=>events.addEventListener(name,stop));
 audio.addEventListener('error',failed);audio.addEventListener('pause',paused);
 return {
  async toggle(){
   if(disposed)return;
   if(wanted || state.playing || state.pending){stop();return;}
   if(visibility.hidden)return;
   const current=++revision;wanted=true;update({pending:true,error:false});
   try {
    await audio.play();
    if(disposed || !wanted || visibility.hidden){audio.pause();return;}
    if(current===revision)update({playing:true,pending:false});
   }catch{
    if(!disposed && current===revision){wanted=false;audio.pause();update({playing:false,pending:false,error:true});}
   }
  },
  dispose(){
   if(disposed)return;
   stop();disposed=true;
   visibility.removeEventListener('visibilitychange',hidden);
   stopEvents.forEach(name=>events.removeEventListener(name,stop));
   audio.removeEventListener('error',failed);audio.removeEventListener('pause',paused);
   audio.removeAttribute('src');audio.load();
  },
 };
}
