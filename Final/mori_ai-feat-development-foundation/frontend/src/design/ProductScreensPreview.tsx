import {useState} from 'react';
import {MemoryRouter} from 'react-router';
import {AlbumCard} from '../features/albums/AlbumCard';
import {UploadPhotoCard} from '../features/uploads/UploadPhotoCard';
import {PhotoStack} from '../features/generation/PhotoStack';
import {GenerationSteps} from '../features/generation/GenerationSteps';
import {CaptionEditor} from '../features/review/CaptionEditor';
import {ThumbnailStrip} from '../features/review/ThumbnailStrip';
import {ViewerNavigation} from '../features/viewer/ViewerNavigation';
import {ScreenHeader} from '../components/layout/ScreenHeader';
import {BottomActionBar} from '../components/layout/BottomActionBar';
import {GlassButton} from '../components/ui/GlassButton';
import {PhotoFrame} from '../components/media/PhotoFrame';
function DemoPhoto({n=0}:{n?:number}){return <div className={`sample-photo sample-photo-${n%4}`} role="img" aria-label="시안에서 가져온 검토용 사진"/>;}
export function ProductScreensPreview({screen}:{screen:string}){
 const [index,setIndex]=useState(0);const [texts,setTexts]=useState(['함께 걸었던 그 바다가 오래도록 생각난다.','바람이 좋았던 오후.','천천히 걸었던 하루.']);const [saved,setSaved]=useState([...texts]);const [message,setMessage]=useState('');const [order,setOrder]=useState([0,1,2,3,4,5]);
 const photo=(n:number)=><DemoPhoto n={n}/>;
 let content;
 if(screen==='bookshelf')content=<section className="bookshelf-screen"><ScreenHeader title="내 책장" subtitle="다시 펼쳐보고 싶은 순간들"/><div className="books">{[0,1,2,3].map(n=><AlbumCard key={n} title="나의 사진첩" meta={`2026. ${9-n}. · 사진 ${12-n}장`} destination="/" cover={<div className="cover">{photo(n)}</div>} status={n===1?'만드는 중':undefined} menu={<details className="book-options"><summary aria-label="사진첩 더보기">···</summary><button onClick={()=>setMessage('검토용 사진첩입니다.')}>삭제</button></details>}/>)}</div><BottomActionBar><GlassButton onClick={()=>setMessage('실제 생성은 별도 로컬 앱에서 확인할 수 있습니다.')}>＋ 새 사진첩</GlassButton></BottomActionBar></section>;
 else if(screen==='upload')content=<section className="album-editor"><ScreenHeader title="사진 고르기" subtitle="사진 한 장이 한 페이지가 돼요"/><span className="sort-state">직접 정한 순서 · 6장</span><ol className="pages">{order.map((n,i)=><UploadPhotoCard key={n} position={i+1} photo={<div className="photo">{photo(n)}</div>} status="준비 완료" actions={<><button disabled={i===0} onClick={()=>setOrder(old=>{const next=[...old];[next[i-1],next[i]]=[next[i],next[i-1]];return next;})}>앞으로</button><button onClick={()=>setMessage('검토용 사진입니다.')}>삭제</button></>}/>)}</ol><GlassButton variant="secondary" onClick={()=>setMessage('실제 파일 선택은 로컬 앱에서 가능합니다.')}>＋ 사진 추가</GlassButton><BottomActionBar><GlassButton onClick={()=>setMessage('검토 화면에서는 AI를 호출하지 않습니다.')}>6장으로 사진첩 만들기 ›</GlassButton></BottomActionBar></section>;
 else if(screen==='generation')content=<section className="generation-screen"><div className="section-heading"><div><span className="generation-brand">mori</span><h1>추억을 엮고 있어요</h1><p>사진과 한 문장을 차곡차곡 담고 있어요.</p></div></div><PhotoStack photos={[0,1,2].map(photo)}/><div className="progress-summary"><p>6장 중 3장 완료</p><progress value={3} max={6}/></div><GenerationSteps steps={[{label:'사진 준비',status:'complete'},{label:'사진첩 만들기',status:'running'},{label:'마무리',status:'pending'}]}/><p className="generation-continue">책장으로 이동해도 계속 만들어요</p><BottomActionBar><GlassButton onClick={()=>setMessage('진행률은 검토용 고정값입니다.')}>책장으로</GlassButton></BottomActionBar></section>;
 else if(screen==='review')content=<section className="review-screen concept-review"><ScreenHeader title="사진첩 확인" trailing={<span>{index+1} / 3</span>}/><div className="review-current"><PhotoFrame>{photo(index)}</PhotoFrame><CaptionEditor value={texts[index]} count={[...texts[index]].length} disabled={false} invalid={[...texts[index]].length>80} onChange={text=>setTexts(old=>old.map((v,i)=>i===index?text:v))} actions={<GlassButton disabled={texts[index]===saved[index]||[...texts[index]].length>80} onClick={()=>setSaved(old=>old.map((v,i)=>i===index?texts[index]:v))}>저장</GlassButton>}/></div><ThumbnailStrip activeId={String(index)} onSelect={id=>setIndex(Number(id))} items={texts.map((text,n)=>({id:String(n),label:`${n+1}번째 사진`,dirty:text!==saved[n],content:photo(n)}))}/><BottomActionBar><GlassButton disabled={texts.some((v,i)=>v!==saved[i])} onClick={()=>setMessage('검토용 완성 동작입니다.')}>사진첩 완성</GlassButton></BottomActionBar></section>;
 else content=<section className="album-viewer"><PhotoFrame>{photo(index)}</PhotoFrame><p className="viewer-caption">{texts[index]}</p><ViewerNavigation index={index} total={3} onPrevious={()=>setIndex(i=>Math.max(0,i-1))} onNext={()=>setIndex(i=>Math.min(2,i+1))}/><p className="hint">음악 재생은 별도 로컬 앱에서 확인합니다.</p></section>;
 return <MemoryRouter><div className="product-preview">{content}<p role="status">{message}</p></div></MemoryRouter>;
}
