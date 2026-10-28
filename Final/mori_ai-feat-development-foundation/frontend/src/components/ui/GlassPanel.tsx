import type {HTMLAttributes} from 'react';
export function GlassPanel({className='',...props}:HTMLAttributes<HTMLDivElement>){return <div {...props} className={`mori-panel ${className}`}/>;}
