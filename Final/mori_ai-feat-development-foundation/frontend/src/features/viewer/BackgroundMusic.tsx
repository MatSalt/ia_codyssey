import { useEffect, useRef, useState } from 'react';
import type { Viewer } from '../../api/types';
import { createMusicPlayback, type MusicState } from './musicPlayback';

export function BackgroundMusic({music}:{music:Viewer['music']}) {
 const audio=useRef<HTMLAudioElement|null>(null);
 const control=useRef<ReturnType<typeof createMusicPlayback>|null>(null);
 const [state,setState]=useState<MusicState>({playing:false,pending:false,error:false});
 useEffect(()=>{
  setState({playing:false,pending:false,error:false});
  if(!music || !audio.current)return;
  const playback=createMusicPlayback(audio.current,music.url,document,window,setState);
  control.current=playback;
  return()=>{control.current=null;playback.dispose();};
 },[music?.url,music?.track_id]);
 if(!music)return <p className="music-note">배경음악을 사용할 수 없습니다.</p>;
 return <div className="viewer-music" onPointerDown={e=>e.stopPropagation()} onPointerUp={e=>e.stopPropagation()} onClick={e=>e.stopPropagation()} onKeyDown={e=>e.stopPropagation()}>
  <audio ref={audio} preload="none" aria-label={music.title}/>
  <button type="button" className="secondary" aria-pressed={state.playing} onClick={()=>void control.current?.toggle()}>
   {state.pending?'음악 불러오기 취소':state.playing?'배경음악 끄기':'배경음악 켜기'}
  </button>
  <p className="music-note" role={state.error?'alert':'status'}>{state.error?'음악을 재생하지 못했습니다. 연결을 확인하고 다시 켜 주세요.':state.pending?'음악을 불러오는 중…':state.playing?'배경음악 재생 중':'버튼을 누르면 음악과 함께 감상할 수 있어요.'}</p>
 </div>;
}
