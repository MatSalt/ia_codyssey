import type {ReactNode} from 'react';
export function PhotoStack({photos}:{photos:ReactNode[]}){return <div className="photo-stack" aria-hidden="true">{[0,1,2].map(i=><div className={`photo-stack-card photo-stack-card-${i}`} key={i}>{photos[i]??<span>mori</span>}</div>)}</div>;}
