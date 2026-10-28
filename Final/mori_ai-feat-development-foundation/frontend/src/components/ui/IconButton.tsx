import type {ButtonHTMLAttributes} from 'react';
export function IconButton({label,className='',type='button',...props}:ButtonHTMLAttributes<HTMLButtonElement>&{label:string}) {
 return <button {...props} type={type} aria-label={label} className={`mori-icon-button ${className}`}/>;
}
