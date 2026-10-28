import type {ReactNode} from 'react';
import {Link} from 'react-router';
export function AlbumCard({title,meta,cover,status,destination,menu}:{title:string;meta:string;cover:ReactNode;status?:ReactNode;destination:string;menu:ReactNode}) {return <article className="album-card"><Link className="album-card-link" to={destination}><div className="album-card-cover">{cover}{status&&<span className="album-card-status">{status}</span>}</div><h2>{title}</h2><p>{meta}</p></Link><div className="album-card-menu">{menu}</div></article>;}
