import test from 'node:test';
import assert from 'node:assert/strict';
const {prepareFiles, inspectImage, resizeDimensions} = await import(process.argv[2]);
function jpeg(w=6000,h=2000,extra=[]) {
 const segment=(marker,body)=>[255,marker,(body.length+2)>>8,(body.length+2)&255,...body];
 return new File([new Uint8Array([255,216,...extra,...segment(192,[8,h>>8,h&255,w>>8,w&255,3,1,17,0,2,17,0,3,17,0]),255,218,0,2,...new Array(200).fill(0),255,217])],'photo.jpg',{type:'image/jpeg',lastModified:1234});
}
function exif(orientation=6) {
 const b=new Uint8Array(110);const d=new DataView(b.buffer);b.set([73,73,42,0,8,0,0,0]);
 d.setUint16(8,2,true);
 d.setUint16(10,274,true);d.setUint16(12,3,true);d.setUint32(14,1,true);d.setUint16(18,orientation,true);
 d.setUint16(22,34665,true);d.setUint16(24,4,true);d.setUint32(26,1,true);d.setUint32(30,38,true);
 d.setUint16(38,2,true);
 for(const [p,tag,count,offset] of [[40,36867,20,68],[52,36881,7,88]]) {d.setUint16(p,tag,true);d.setUint16(p+2,2,true);d.setUint32(p+4,count,true);d.setUint32(p+8,offset,true);}
 b.set(new TextEncoder().encode('2020:01:02 03:04:05\0'),68);b.set(new TextEncoder().encode('+09:00\0'),88);
 const body=[69,120,105,102,0,0,...b];return [255,225,(body.length+2)>>8,(body.length+2)&255,...body];
}
let closed, canvases, decodes, active, maxActive, encodeType, encodeSize, failDecode, onDecode;
function browser() {
 closed=0;canvases=[];decodes=0;active=0;maxActive=0;encodeType='image/webp';encodeSize=24;failDecode=false;onDecode=undefined;
 globalThis.createImageBitmap=async blob=>{decodes++; active++; maxActive=Math.max(maxActive,active);await Promise.resolve();if(failDecode){active--;throw Error('decode');} const info=inspectImage(new Uint8Array(await blob.arrayBuffer()),'image/jpeg');onDecode?.();return {width:info.width,height:info.height,close(){closed++;active--;}};};
 globalThis.document={createElement(){const canvas={width:0,height:0,getContext(){return {transform(...v){canvas.matrix=v;},drawImage(){}};},toBlob(cb,type,q){canvas.quality=q;const b=new Uint8Array(encodeSize);b.set([82,73,70,70,16,0,0,0,87,69,66,80]);cb(new Blob([b],{type:encodeType}));}};canvases.push(canvas);return canvas;}};
}
const signal=()=>new AbortController().signal;
test('resize bounds preserve near 3:4 distinction without stretching or upscaling',()=>{
 assert.deepEqual(resizeDimensions(6000,2000),[4096,1365]);assert.deepEqual(resizeDimensions(3000,4000),[3000,4000]);
});
test('safe JPEG conversion is smaller WebP with original dimensions and immutable modified time',async()=>{
 browser();const original=jpeg();const [out]=await prepareFiles([original],signal());
 assert.notEqual(out.file,original);assert.equal(out.file.type,'image/webp');assert.equal(out.file.name,'photo.webp');assert.equal(out.file.lastModified,1234);
 assert.deepEqual(out.preprocessing,{version:1,original_width:6000,original_height:2000,captured_at_raw:null,captured_timezone:null});
 assert.equal(canvases[0].quality,.9);assert.equal(closed,1);assert.equal(canvases[0].width,0);
});
test('EXIF orientation/date are extracted before metadata-free decode',async()=>{
 browser();const [out]=await prepareFiles([jpeg(4000,3000,exif())],signal());
 assert.deepEqual(out.preprocessing,{version:1,original_width:3000,original_height:4000,captured_at_raw:'2020:01:02 03:04:05',captured_timezone:'+09:00'});
 assert.deepEqual(canvases[0].matrix,[0,1,-1,0,3000,0]);
});
test('unsafe color, >12MP, unknown format, malformed EXIF all bypass decode',async()=>{
 browser();const originals=[jpeg(4001,3000),jpeg(100,100,[255,226,0,4,1,2]),jpeg(100,100,[255,225,0,8,69,120,105,102,0,0]),new File(['abc'],'x.heic',{type:'image/heic'})];
 const out=await prepareFiles(originals,signal());out.forEach((v,i)=>assert.equal(v.file,originals[i]));assert.equal(decodes,0);
});
test('unsupported encoder, no saving and decoder failure preserve original and omit hints',async()=>{
 for(const mode of ['mime','size','decode','capability']) {browser();const original=jpeg();if(mode==='mime')encodeType='image/png';if(mode==='size')encodeSize=1000;if(mode==='decode')failDecode=true;if(mode==='capability')delete globalThis.createImageBitmap;
 const [out]=await prepareFiles([original],signal());assert.equal(out.file,original);assert.equal(out.preprocessing,undefined);}
});
test('batch preparation is sequential and abort closes decoded bitmap without starting next file',async()=>{
 browser();await prepareFiles([jpeg(),jpeg(),jpeg()],signal());assert.equal(maxActive,1);assert.equal(closed,3);
 browser();const abort=new AbortController();onDecode=()=>abort.abort();await assert.rejects(prepareFiles([jpeg(),jpeg()],abort.signal),{name:'AbortError'});assert.equal(decodes,1);assert.equal(closed,1);
});
function png(w=100,h=100,chunks=[]) {
 const chunk=(name,data)=>{const b=new Uint8Array(data.length+12);new DataView(b.buffer).setUint32(0,data.length);b.set(new TextEncoder().encode(name),4);b.set(data,8);return b;};
 const ihdr=new Uint8Array(13);const d=new DataView(ihdr.buffer);d.setUint32(0,w);d.setUint32(4,h);ihdr[8]=8;ihdr[9]=6;
 return new File([new Uint8Array([137,80,78,71,13,10,26,10]),chunk('IHDR',ihdr),...chunks.map(([n,b])=>chunk(n,b)),chunk('IDAT',new Uint8Array(200)),chunk('IEND',[])],'alpha.png',{type:'image/png'});
}
test('transparent PNG uses transparent canvas and unsafe PNG color/HDR/animation fall back',async()=>{
 browser();globalThis.createImageBitmap=async()=>({width:100,height:100,close(){closed++;}});
 const [out]=await prepareFiles([png()],signal());assert.equal(out.file.type,'image/webp');assert.equal(out.preprocessing.original_width,100);
 for(const name of ['iCCP','cICP','acTL','tEXt']) {const file=png(100,100,[[name,new Uint8Array(4)]]);assert.equal((await prepareFiles([file],signal()))[0].file,file);}
});
test('all EXIF orientations preserve corrected original dimensions',async()=>{
 const expected=[[1,0,0,1,0,0],[-1,0,0,1,4000,0],[-1,0,0,-1,4000,3000],[1,0,0,-1,0,3000],[0,1,1,0,0,0],[0,1,-1,0,3000,0],[0,-1,-1,0,3000,4000],[0,-1,1,0,0,4000]];
 for(let orientation=1;orientation<=8;orientation++){browser();const [out]=await prepareFiles([jpeg(4000,3000,exif(orientation))],signal());assert.equal(out.preprocessing.original_width,orientation>=5?3000:4000);assert.deepEqual(canvases[0].matrix,expected[orientation-1]);}
});
test('abort during encoding releases canvas and bitmap; no result survives',async()=>{
 browser();const abort=new AbortController();const create=document.createElement;document.createElement=()=>{const c=create();const encode=c.toBlob;c.toBlob=(...args)=>{abort.abort();encode(...args);};return c;};
 await assert.rejects(prepareFiles([jpeg()],abort.signal),{name:'AbortError'});assert.equal(closed,1);assert.equal(canvases[0].height,0);
});
