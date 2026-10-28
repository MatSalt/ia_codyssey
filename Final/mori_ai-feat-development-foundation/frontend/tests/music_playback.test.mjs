import test from 'node:test';
import assert from 'node:assert/strict';
const {createMusicPlayback}=await import(process.argv[2]);
function fixture(){
 const doc=new EventTarget();doc.hidden=false;const win=new EventTarget();const states=[];
 const audio=new EventTarget();audio.paused=true;audio.plays=0;audio.loads=0;
 audio.play=async()=>{audio.plays++;audio.paused=false;};
 audio.pause=()=>{audio.paused=true;};audio.load=()=>{audio.loads++;};audio.removeAttribute=()=>{};
 const controller=createMusicPlayback(audio,'/audio/bgm.mp3',doc,win,s=>states.push(s));
 return {doc,win,audio,states,controller};
}
test('starts only by user action, loops, and toggles off',async()=>{
 const {audio,controller,states}=fixture();assert.equal(audio.plays,0);assert.equal(audio.loop,true);
 await controller.toggle();assert.equal(states.at(-1).playing,true);assert.equal(audio.plays,1);
 await controller.toggle();assert.equal(audio.paused,true);assert.equal(states.at(-1).playing,false);
 controller.dispose();assert.equal(audio.loads,1);
});
test('background and pagehide stop; visibility return does not autoplay',async()=>{
 const {audio,controller,doc,win}=fixture();await controller.toggle();
 doc.hidden=true;doc.dispatchEvent(new Event('visibilitychange'));assert.equal(audio.paused,true);
 doc.hidden=false;doc.dispatchEvent(new Event('visibilitychange'));assert.equal(audio.plays,1);
 await controller.toggle();win.dispatchEvent(new Event('pagehide'));assert.equal(audio.paused,true);
 controller.dispose();
});
test('blocked playback and media errors allow an explicit retry',async()=>{
 const {audio,controller,states}=fixture();audio.play=async()=>{throw new DOMException('private','NotAllowedError');};
 await controller.toggle();assert.equal(states.at(-1).error,true);assert.equal(states.at(-1).pending,false);
 audio.play=async()=>{audio.paused=false;};await controller.toggle();assert.equal(states.at(-1).playing,true);
 audio.dispatchEvent(new Event('error'));assert.equal(states.at(-1).error,true);assert.equal(audio.paused,true);
 controller.dispose();
});
for(const reason of ['hidden','dispose','toggle'])test(`pending play cannot restart after ${reason}`,async()=>{
 const {audio,controller,doc,states}=fixture();let resolve;
 audio.play=()=>new Promise(r=>{resolve=()=>{audio.paused=false;r();};});
 const pending=controller.toggle();assert.equal(states.at(-1).pending,true);
 if(reason==='hidden'){doc.hidden=true;doc.dispatchEvent(new Event('visibilitychange'));}
 else if(reason==='dispose')controller.dispose();else await controller.toggle();
 resolve();await pending;assert.equal(audio.paused,true);assert.equal(states.at(-1).playing,false);
 if(reason!=='dispose')controller.dispose();
});
test('session expiry stops music and disposal removes listeners',async()=>{
 const {audio,controller,win}=fixture();await controller.toggle();win.dispatchEvent(new Event('mori:session-expired'));assert.equal(audio.paused,true);
 controller.dispose();audio.paused=false;win.dispatchEvent(new Event('pagehide'));assert.equal(audio.paused,false);
});
