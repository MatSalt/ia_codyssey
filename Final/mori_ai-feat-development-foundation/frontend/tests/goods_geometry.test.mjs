import test from 'node:test';
import assert from 'node:assert/strict';
const {artworkOutline, nearestEdge, pickEdge} = await import(process.argv[2] || '../src/features/goods/mockup/geometry.ts');
function pixels(w,h,solid){const data=new Uint8Array(w*h*4);for(let y=0;y<h;y++)for(let x=0;x<w;x++)if(solid(x,y))data[(y*w+x)*4+3]=255;return data;}
const rectangle=()=>artworkOutline(pixels(200,200,(x,y)=>x>=30&&x<170&&y>=30&&y<170),200,200);
test('inside and far outside taps do not move hole; near edge snaps',()=>{
 const g=rectangle();assert.equal(pickEdge(g,.5,.5),null);assert.equal(pickEdge(g,-.5,.5),null);
 const p=pickEdge(g,.5,.04);assert.equal(p.y,0);assert.ok(Math.abs(p.x-.5)<.01);
});
test('internal holes and disconnected small pieces are not hole candidates',()=>{
 const g=artworkOutline(pixels(200,200,(x,y)=>(x===0&&y===0)||(x>=30&&x<170&&y>=30&&y<170&&!(x>70&&x<130&&y>70&&y<130))),200,200);
 assert.ok(g.anchors.every(p=>p.x>.1));assert.equal(pickEdge(g,.5,.5),null);
});
test('portrait uses physical distance; changing width changes allowed proximity',()=>{
 const g=artworkOutline(pixels(80,200,(x,y)=>x>=10&&x<70&&y>=20&&y<180),80,200);
 assert.ok(pickEdge(g,.05,.5));assert.equal(pickEdge(g,.5,.5),null);
 assert.ok(pickEdge(rectangle(),.08,.5,50));assert.equal(pickEdge(rectangle(),.08,.5,100),null);
});
test('exact alpha bounds survive preview downsampling for PDF alignment',()=>{
 const g=artworkOutline(pixels(1000,300,(x,y)=>x>=123&&x<878&&y>=51&&y<249),1000,300);
 assert.deepEqual(g.bounds,{x:123,y:51,width:755,height:198});
 assert.equal(g.aspect,198/755);
});
test('ellipse anchors stay within artwork bounds',()=>{
 const g=artworkOutline(pixels(200,200,(x,y)=>((x-100)/70)**2+((y-100)/90)**2<1),200,200);
 assert.ok(g.anchors.every(p=>p.x>=0&&p.x<=1&&p.y>=0&&p.y<=1));
 assert.ok(pickEdge(g,.5,.01));assert.equal(pickEdge(g,.5,.5),null);
});
test('transparent, malformed buffers and unsafe coordinates are rejected',()=>{
 assert.throws(()=>artworkOutline(new Uint8Array(16),2,2));
 for(const [w,h,d] of [[0,2,16],[-1,2,16],[2.5,2,20],[2,2,15],[Infinity,1,4]])assert.throws(()=>artworkOutline(new Uint8Array(d),w,h));
 assert.throws(()=>nearestEdge(rectangle(),NaN,.5));assert.throws(()=>pickEdge(rectangle(),.5,.5,0));
});
