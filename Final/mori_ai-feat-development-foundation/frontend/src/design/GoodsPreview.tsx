import {createRoot} from 'react-dom/client';
import {GoodsDesigner} from '../features/goods/design/GoodsDesigner';
import type {DesignStyle} from '../features/goods/design/catalog';
import '../styles.css';
import '../features/goods/goods.css';
const styles:DesignStyle[]=[{id:'photo',label:'사진형 액자',hint:'사진을 작은 액자처럼'},{id:'illustration',label:'사진을 그림으로',hint:'구도는 살리고 그림체만'},{id:'cutout',label:'인물·반려동물',hint:'배경 없이 주인공만'},{id:'badge',label:'여행·문구',hint:'상징물과 글자를 한 모양에'},{id:'book',label:'추억을 펼친 책',hint:'그림과 문구를 오픈북에'},{id:'free',label:'자유롭게',hint:'원하는 모양을 말로 설명'}];
createRoot(document.getElementById('root')!).render(<><p className="goods-preview-notice">화면 미리보기 · 파일은 이 화면에서만 확인하며 주문으로 접수되지 않아요.</p><GoodsDesigner styles={styles}/></>);
