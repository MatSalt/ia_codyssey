import type {ButtonHTMLAttributes} from 'react';
export function GlassButton({variant='primary',className='',type='button',...props}:ButtonHTMLAttributes<HTMLButtonElement>&{variant?:'primary'|'secondary'|'danger'}) {
 return <button {...props} type={type} className={`mori-button mori-button--${variant} ${className}`}/>;
}
