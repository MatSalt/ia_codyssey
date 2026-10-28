// Adapted from mori-memory-pilot fb5a3418; see frontend/public/goods/PROVENANCE.md.
export const ARTWORK_WIDTH_MM=50, BORDER_MM=2, EYELET_RADIUS_MM=3.5, HOLE_RADIUS_MM=1.5, PICK_DISTANCE_MM=5;
export type Point={x:number;y:number};
export type Outline={bounds:{x:number;y:number;width:number;height:number};anchors:Point[];aspect:number};
// Main connected subject + flood-filled outside air exclude internal holes.
export function artworkOutline(rgba:ArrayLike<number>,width:number,height:number):Outline{
 if(!Number.isSafeInteger(width)||!Number.isSafeInteger(height)||width<=0||height<=0||width*height>16_000_000||rgba.length!==width*height*4)throw new Error('지원하지 않는 그림 크기입니다.');
 let exactLeft=width,exactTop=height,exactRight=-1,exactBottom=-1;
 for(let y=0;y<height;y++)for(let x=0;x<width;x++)if(rgba[(y*width+x)*4+3]>48){exactLeft=Math.min(exactLeft,x);exactRight=Math.max(exactRight,x);exactTop=Math.min(exactTop,y);exactBottom=Math.max(exactBottom,y);}
 if(exactRight<exactLeft)throw new Error('구멍을 배치할 그림을 찾지 못했어요.');
 const exactW=exactRight-exactLeft+1,exactH=exactBottom-exactTop+1;
 const scale=Math.min(1,256/Math.max(width,height)),sw=Math.max(1,Math.round(width*scale)),sh=Math.max(1,Math.round(height*scale)),stride=sw+2,total=stride*(sh+2);
 const solid=new Uint8Array(total),labels=new Uint32Array(total),air=new Uint8Array(total),queue=new Int32Array(total),neighbors=[-1,1,-stride,stride];
 let minX=sw,minY=sh,maxX=-1,maxY=-1;
 for(let y=0;y<sh;y++)for(let x=0;x<sw;x++){
  const sx=Math.min(width-1,Math.floor((x+.5)*width/sw)),sy=Math.min(height-1,Math.floor((y+.5)*height/sh));
  if(rgba[(sy*width+sx)*4+3]>48){solid[(y+1)*stride+x+1]=1;minX=Math.min(minX,x);maxX=Math.max(maxX,x);minY=Math.min(minY,y);maxY=Math.max(maxY,y);}
 }
 if(maxX<minX)throw new Error('구멍을 배치할 그림을 찾지 못했어요.');
 let nextLabel=0,largest=0,largestSize=0;
 for(let i=0;i<total;i++)if(solid[i]&&!labels[i]){
  const label=++nextLabel;let head=0,tail=1;queue[0]=i;labels[i]=label;
  while(head<tail){const p=queue[head++];for(const d of neighbors){const n=p+d;if(n>=0&&n<total&&solid[n]&&!labels[n]){labels[n]=label;queue[tail++]=n;}}}
  if(tail>largestSize){largestSize=tail;largest=label;}
 }
 let head=0,tail=1;queue[0]=0;air[0]=1;
 while(head<tail){const p=queue[head++],px=p%stride;for(const d of neighbors){if(d===-1&&px===0||d===1&&px===stride-1)continue;const n=p+d;if(n>=0&&n<total&&!solid[n]&&!air[n]){air[n]=1;queue[tail++]=n;}}}
 const anchors:Point[]=[],bw=maxX-minX+1,bh=maxY-minY+1;
 for(let y=0;y<sh;y++)for(let x=0;x<sw;x++){
  const p=(y+1)*stride+x+1;if(labels[p]!==largest||!neighbors.some(d=>air[p+d]))continue;
  const dx=Number(!!air[p+1])-Number(!!air[p-1]),dy=Number(!!air[p+stride])-Number(!!air[p-stride]),len=Math.hypot(dx,dy)||1;
  anchors.push({x:Math.max(0,Math.min(1,((x+.5+dx/len*.5)/sw*width-exactLeft)/exactW)),y:Math.max(0,Math.min(1,((y+.5+dy/len*.5)/sh*height-exactTop)/exactH))});
 }
 if(!anchors.length)throw new Error('그림의 테두리를 찾지 못했어요.');
 return {bounds:{x:exactLeft,y:exactTop,width:exactW,height:exactH},anchors,aspect:exactH/exactW};
}
export function nearestEdge(outline:Outline,x:number,y:number):Point{
 if(!Number.isFinite(x)||!Number.isFinite(y)||!outline.anchors.length)throw new Error('구멍 좌표를 확인해 주세요.');
 const distance=(p:Point)=>(p.x-x)**2+((p.y-y)*outline.aspect)**2;
 return outline.anchors.reduce((best,p)=>distance(p)<distance(best)?p:best);
}
export function pickEdge(outline:Outline,x:number,y:number,widthMm=ARTWORK_WIDTH_MM):Point|null{
 if(!Number.isFinite(widthMm)||widthMm<=0)throw new Error('그림 폭을 확인해 주세요.');
 const p=nearestEdge(outline,x,y),distance=Math.hypot(p.x-x,(p.y-y)*outline.aspect)*widthMm;
 return distance<=PICK_DISTANCE_MM?p:null;
}
