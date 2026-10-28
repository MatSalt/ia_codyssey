import type {CSSProperties,ReactNode} from 'react';
export const photoNames=['바다의 기억','나무 아래에서','햇살 가득한 오후','작은 마을','함께한 식탁','노을빛 바다'];
const crops=[[110,400,240,320],[500,400,240,320],[110,790,240,320],[500,790,240,320],[110,1180,240,320],[500,1180,240,320]];
export function Photo({index=0,kind='tile',className=''}:{index?:number;kind?:'tile'|'login'|'review'|'viewer';className?:string}){
 let source='03-photo-upload',rect=crops[index%6];
 if(kind==='login'){source='01-login';rect=[90,485,640,800];}
 if(kind==='review'){source='05-caption-review';rect=[60,235,720,960];}
 if(kind==='viewer'){source='06-viewer-bgm';rect=[6,240,840,1120];}
 const [x,y,w,h]=rect;
 const style={backgroundImage:`url('/design-preview/${source}.png')`,backgroundSize:`${852/w*100}% ${1846/h*100}%`,backgroundPosition:`${x/(852-w||1)*100}% ${y/(1846-h)*100}%`} as CSSProperties;
 return <div className={'concept-photo '+className} style={style} role="img" aria-label={kind==='review'?'바닷가를 함께 걷는 가족':kind==='login'?'바다를 바라보는 사람':kind==='viewer'?'노을지는 해변':photoNames[index%6]}/>;
}
export function Topbar({title='mori',back,onBack,children}:{title?:string;back?:boolean;onBack?:()=>void;children?:ReactNode}){return <nav className="screen-top" aria-label="화면 이동">{back?<button className="glass-control round" aria-label="이전 화면 시연" onClick={onBack}>‹</button>:<span/>}<span className={title==='mori'?'wordmark':'top-title'}>{title}</span><div>{children}</div></nav>}
export function Action({children,onClick,disabled=false}:{children:ReactNode;onClick?:()=>void;disabled?:boolean}){return <div className="screen-action"><button className="primary" onClick={onClick} disabled={disabled}>{children}</button></div>}
export function Note({children,error=false}:{children:ReactNode;error?:boolean}){return children?<p className={'message '+(error?'error':'')} role={error?'alert':'status'}>{children}</p>:null;}
