import {GlassButton} from '../../../components/ui/GlassButton';
import {GlassPanel} from '../../../components/ui/GlassPanel';
import {PhotoFrame} from '../../../components/media/PhotoFrame';
export type RevisionItem = {id:string;label:string} & ({status:'ready';imageUrl:string}|{status:'pending'|'failed'});
export function RevisionHistory({items,selectedId,disabled=false,onSelect}:{items:RevisionItem[];selectedId:string|null;disabled?:boolean;onSelect:(id:string)=>void}) {
  if(!items.length)return <GlassPanel><p>아직 시안이 없어요.</p><p className="goods-note">완성된 시안을 여기에서 다시 선택할 수 있어요.</p></GlassPanel>;
  return <section aria-label="시안 이력" className="goods-revisions">{items.map(item=><GlassPanel key={item.id} className="goods-revision">
    <h3>{item.label}</h3>
    {item.status==='ready'?<><PhotoFrame ratio="square"><img src={item.imageUrl} alt={item.label}/></PhotoFrame><GlassButton variant="secondary" disabled={disabled} aria-pressed={selectedId===item.id} onClick={()=>onSelect(item.id)}>{selectedId===item.id?'선택한 시안':'이 시안 선택'}</GlassButton></>:<p role="status">{item.status==='pending'?'시안을 만드는 중이에요.':'시안을 생성하지 못했어요.'}</p>}
  </GlassPanel>)}</section>;
}
