// Adapted from mori-memory-pilot fb5a3418; see frontend/public/goods/PROVENANCE.md.
import {BORDER_MM,EYELET_RADIUS_MM,HOLE_RADIUS_MM,artworkOutline,nearestEdge} from './geometry';
import type {Outline} from './geometry';
export type CharmGeometry={left:number;top:number;w:number;h:number;outline:Outline};
export const CHARM_WIDTH=800,CHARM_HEIGHT=840;
function surface(mask:HTMLCanvasElement,paint:string|CanvasGradient){
 const layer=document.createElement('canvas');layer.width=CHARM_WIDTH;layer.height=CHARM_HEIGHT;
 const ctx=layer.getContext('2d')!;ctx.drawImage(mask,0,0);ctx.globalCompositeOperation='source-in';ctx.fillStyle=paint;ctx.fillRect(0,0,CHARM_WIDTH,CHARM_HEIGHT);return layer;
}
// Composite real hardware with deterministic artwork/edge geometry. The exported PNG uses this same renderer.
export function renderCharm(out:HTMLCanvasElement,img:HTMLImageElement,hardware:HTMLImageElement|null,product:string,placement:{holeX:number;holeY:number;widthMm:number}):CharmGeometry{
 if(!Number.isSafeInteger(img.naturalWidth)||!Number.isSafeInteger(img.naturalHeight)||img.naturalWidth<=0||img.naturalHeight<=0||img.naturalWidth*img.naturalHeight>16_000_000)throw new Error('지원하지 않는 그림 크기입니다.');
 if(!Number.isFinite(placement.widthMm)||placement.widthMm<=0)throw new Error('그림 폭을 확인해 주세요.');
 if(![placement.holeX,placement.holeY].every(n=>Number.isFinite(n)&&n>=0&&n<=1))throw new Error('구멍 위치를 확인해 주세요.');
 if(product!=='keyring'&&product!=='magnet')throw new Error('지원하지 않는 상품입니다.');
 const scan=document.createElement('canvas');scan.width=img.naturalWidth;scan.height=img.naturalHeight;
 const sc=scan.getContext('2d')!;sc.drawImage(img,0,0);
 const outline=artworkOutline(sc.getImageData(0,0,scan.width,scan.height).data,scan.width,scan.height),b=outline.bounds;
 scan.width=0;scan.height=0;
 const keyring=product==='keyring',scale=Math.min(560/b.width,510/b.height),w=b.width*scale,h=b.height*scale,left=(CHARM_WIDTH-w)/2,top=(keyring?250:165)+(510-h)/2;
 out.width=CHARM_WIDTH;out.height=CHARM_HEIGHT;const c=out.getContext('2d')!;
 c.imageSmoothingEnabled=true;c.imageSmoothingQuality='high';
 const art=document.createElement('canvas');art.width=Math.ceil(w);art.height=Math.ceil(h);art.getContext('2d')!.drawImage(img,b.x,b.y,b.width,b.height,0,0,w,h);
 const mask=document.createElement('canvas');mask.width=art.width;mask.height=art.height;
 const mc=mask.getContext('2d')!;mc.drawImage(art,0,0);mc.globalCompositeOperation='source-in';mc.fillStyle='#fff';mc.fillRect(0,0,w,h);
 const rim=w*BORDER_MM/placement.widthMm,anchor=nearestEdge(outline,placement.holeX,placement.holeY),hx=left+anchor.x*w,hy=top+anchor.y*h,eyelet=w*EYELET_RADIUS_MM/placement.widthMm,hole=w*HOLE_RADIUS_MM/placement.widthMm;
 const body=document.createElement('canvas');body.width=CHARM_WIDTH;body.height=CHARM_HEIGHT;const bc=body.getContext('2d')!;
 for(let a=0;a<Math.PI*2;a+=Math.PI/32)bc.drawImage(mask,left+Math.cos(a)*rim,top+Math.sin(a)*rim);
 bc.drawImage(mask,left,top);
 if(keyring){bc.fillStyle='#fff';bc.beginPath();bc.arc(hx,hy,eyelet,0,Math.PI*2);bc.fill();bc.globalCompositeOperation='destination-out';bc.beginPath();bc.arc(hx,hy,hole,0,Math.PI*2);bc.fill();}
 // One soft contact shadow, then a thin polished sidewall and a bright front bevel.
 c.save();c.shadowColor='rgba(30,35,41,.22)';c.shadowBlur=24;c.shadowOffsetX=5;c.shadowOffsetY=13;c.drawImage(surface(body,'#a9afb3'),2,5);c.restore();
 const edge=c.createLinearGradient(100,160,700,790);edge.addColorStop(0,'#ffffff');edge.addColorStop(.25,'#bdc3c7');edge.addColorStop(.5,'#f2f4f5');edge.addColorStop(.85,'#a8afb4');edge.addColorStop(1,'#e6e8e9');
 c.drawImage(surface(body,edge),1,3);
 const face=c.createLinearGradient(0,180,650,780);face.addColorStop(0,'#fff');face.addColorStop(.45,'#f3f5f6');face.addColorStop(.7,'#e7ebed');face.addColorStop(1,'#fcfdfd');c.drawImage(surface(body,face),0,0);
 const inset=document.createElement('canvas');inset.width=CHARM_WIDTH;inset.height=CHARM_HEIGHT;const ic=inset.getContext('2d')!;
 ic.drawImage(body,0,0);ic.globalCompositeOperation='destination-out';ic.drawImage(body,1.8,2.5);c.drawImage(surface(inset,'rgba(255,255,255,.92)'),0,0);
 // Print remains unchanged. Reflective treatment belongs to the clear acrylic border.
 c.drawImage(art,left,top);
 if(keyring){
  c.save();c.globalCompositeOperation='destination-out';c.beginPath();c.arc(hx,hy,hole,0,Math.PI*2);c.fill();c.restore();
  c.beginPath();c.arc(hx,hy,hole+1,0,Math.PI*2);c.strokeStyle='rgba(105,116,125,.5)';c.lineWidth=1.5;c.stroke();
  c.beginPath();c.arc(hx-1,hy-1,Math.max(0,eyelet-2),Math.PI*.9,Math.PI*1.75);c.strokeStyle='rgba(255,255,255,.9)';c.lineWidth=2;c.stroke();
  if(hardware){
   // Bottom arc enters the hole; the clasp follows the selected edge position.
   const size=230,hw=size*.82,ax=hx-hw*.488,ay=hy+hole*.35-size*.92;
   c.save();c.shadowColor='rgba(36,42,48,.18)';c.shadowBlur=5;c.shadowOffsetY=3;c.drawImage(hardware,ax,ay,hw,size);c.restore();
  }
 }
 return {left,top,w,h,outline};
}
