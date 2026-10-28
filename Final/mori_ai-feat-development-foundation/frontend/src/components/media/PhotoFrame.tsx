import type {ReactNode} from 'react';
export function PhotoFrame({children,ratio='portrait',fit='contain'}:{children:ReactNode;ratio?:'portrait'|'square';fit?:'contain'|'cover'}) {
 return <div className={`mori-photo mori-photo--${ratio} mori-photo--${fit}`}>{children}</div>;
}
