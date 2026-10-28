import test from 'node:test';
import assert from 'node:assert/strict';
const {renderCharm}=await import(process.argv[2]);
test('invalid image size and unsupported placement fail before canvas allocation',()=>{
 let allocations=0;globalThis.document={createElement(){allocations++;throw Error('must not allocate');}};
 const valid={naturalWidth:100,naturalHeight:100};
 for(const image of [{naturalWidth:0,naturalHeight:100},{naturalWidth:5000,naturalHeight:5000}])assert.throws(()=>renderCharm({},image,null,'magnet',{holeX:.5,holeY:0,widthMm:50}),/크기/);
 for(const placement of [{holeX:NaN,holeY:0,widthMm:50},{holeX:.5,holeY:0,widthMm:0},{holeX:1.5,holeY:0,widthMm:50}])assert.throws(()=>renderCharm({},valid,null,'keyring',placement),/위치|폭/);
 assert.equal(allocations,0);
});
test('very tall artwork never asks Canvas for a negative arc radius',()=>{
 const rgba=new Uint8Array(20*400*4);for(let i=3;i<rgba.length;i+=4)rgba[i]=255;
 const context={drawImage(){},fillRect(){},clearRect(){},save(){},restore(){},beginPath(){},fill(){},stroke(){},
  arc(_x,_y,r){if(r<0)throw new DOMException('negative radius','IndexSizeError');},
  getImageData(){return {data:rgba};},createLinearGradient(){return {addColorStop(){}};}};
 const canvas=()=>({width:0,height:0,getContext(){return context;}});
 globalThis.document={createElement(){return canvas();}};
 assert.doesNotThrow(()=>renderCharm(canvas(),{naturalWidth:20,naturalHeight:400},null,'keyring',{holeX:.5,holeY:0,widthMm:50}));
});
