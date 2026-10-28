import {useRef,useState} from 'react';
import {GlassButton} from '../../../components/ui/GlassButton';
import {IconButton} from '../../../components/ui/IconButton';
import {PhotoFrame} from '../../../components/media/PhotoFrame';
import {exampleImage} from './catalog';
import type {DesignStyle, StyleId} from './catalog';
import type {GoodsProduct} from '../mockup/preview';
export function StylePicker({styles,product,selected,disabled=false,onSelect}:{styles:DesignStyle[];product:GoodsProduct;selected:StyleId|null;disabled?:boolean;onSelect:(id:StyleId)=>void}) {
  const track=useRef<HTMLDivElement>(null);const [active,setActive]=useState(0);
  function move(index:number){const card=track.current?.children[index];if(card)card.scrollIntoView({block:'nearest',inline:'center',behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});}
  function scrolled(){const el=track.current;if(!el)return;const rect=el.getBoundingClientRect(),center=rect.left+rect.width/2;let best=0,distance=Infinity;Array.from(el.children).forEach((card,i)=>{const r=card.getBoundingClientRect(),d=Math.abs(r.left+r.width/2-center);if(d<distance){distance=d;best=i;}});setActive(best);}
  return <section aria-label="디자인 형태 선택" aria-roledescription="캐러셀">
    <div ref={track} className="goods-style-track" onScroll={scrolled}>{styles.map(style=><GlassButton key={style.id} variant="secondary" className="goods-style" disabled={disabled} aria-pressed={selected===style.id} onClick={()=>onSelect(style.id)}>
      <PhotoFrame ratio="square" fit="contain"><img src={exampleImage(product,style.id,true)} alt="" loading="lazy" draggable={false}/></PhotoFrame>
      <span className="goods-style-label">{style.label}</span><span className="goods-note">{style.hint}</span>
      <span className="goods-card-action">{selected===style.id?'선택한 모양':'이 모양 선택'}</span>
    </GlassButton>)}</div>
    <div className="goods-slide-nav"><IconButton label="이전 모양" disabled={active===0||disabled} onClick={()=>move(active-1)}>‹</IconButton><span aria-live="polite">{styles.length?active+1:0} / {styles.length}</span><IconButton label="다음 모양" disabled={active>=styles.length-1||disabled} onClick={()=>move(active+1)}>›</IconButton></div>
    <p className="goods-note">옆으로 넘겨 모양을 골라 보세요. 이미지는 형태를 참고하기 위한 예시입니다.</p>
  </section>;
}
