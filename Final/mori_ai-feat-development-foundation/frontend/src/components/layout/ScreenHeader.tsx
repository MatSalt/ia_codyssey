import type {ReactNode} from 'react';
export function ScreenHeader({title,subtitle,leading,trailing}:{title:string;subtitle?:string;leading?:ReactNode;trailing?:ReactNode}) {
 return <header className="mori-screen-header">{leading && <div className="mori-header-leading">{leading}</div>}<div><h1>{title}</h1>{subtitle && <p>{subtitle}</p>}</div>{trailing && <div className="mori-header-trailing">{trailing}</div>}</header>;
}
