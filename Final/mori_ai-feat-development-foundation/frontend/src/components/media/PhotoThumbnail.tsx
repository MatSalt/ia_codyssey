import type {ReactNode} from 'react';
export function PhotoThumbnail({label,selected,onSelect,children}:{label:string;selected:boolean;onSelect:()=>void;children:ReactNode}) {
 return <button type="button" className="mori-thumbnail" aria-label={label} aria-pressed={selected} onClick={onSelect}>{children}</button>;
}
