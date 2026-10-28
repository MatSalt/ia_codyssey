import test from 'node:test';
import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {mkdtemp,writeFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
const temp=await mkdtemp(join(tmpdir(),'mori-preprocess-'));
const result=await build({entryPoints:['src/features/uploads/useUploads.ts'],bundle:true,platform:'node',format:'esm',write:false,plugins:[{name:'hooks',setup(b){b.onResolve({filter:/^react$/},()=>({path:'hooks',namespace:'test'}));b.onLoad({filter:/.*/,namespace:'test'},()=>({contents:`export const useRef=(v)=>globalThis.hooks.ref(v);export const useState=(v)=>globalThis.hooks.state(v);export const useEffect=(f)=>globalThis.hooks.effect(f);`}));}}]});
await writeFile(join(temp,'hook.mjs'),result.outputFiles[0].text);
globalThis.window=new EventTarget();window.location={origin:'http://localhost'};
const {useUploads}=await import(join(temp,'hook.mjs'));
function harness() {
 let cursor=0;const cells=[];const cleanups=[];let initial=true;
 globalThis.hooks={ref(v){const i=cursor++;return cells[i]??=( {current:v});},state(v){const i=cursor++;if(!(i in cells))cells[i]=v;return [cells[i],next=>{cells[i]=next;}];},effect(f){if(initial)cleanups.push(f());}};
 return {render(){cursor=0;const h=useUploads('a','u',async()=>{});initial=false;return h;},cleanup(){cleanups.forEach(f=>f());}};
}
function browser() {
 let decodes=0;globalThis.createImageBitmap=async()=>{decodes++;return {width:100,height:100,close(){}};};
 globalThis.document={createElement:()=>({getContext:()=>({transform(){},drawImage(){}}),toBlob:cb=>cb(new Blob([new Uint8Array([82,73,70,70,16,0,0,0,87,69,66,80,0,0,0,0])],{type:'image/webp'}))})};
 return ()=>decodes;
}
function photo(){return new File([new Uint8Array([255,216,255,192,0,17,8,0,100,0,100,3,1,17,0,2,17,0,3,17,0,255,218,0,2,...new Array(200).fill(0)])],'original.jpg',{type:'image/jpeg',lastModified:1234});}
const response=data=>new Response(JSON.stringify({data}),{status:200,headers:{'Content-Type':'application/json'}});
test('reservation retry retains body/key and PUT retries retain identical prepared File and digest',async()=>{
 const decoded=browser(),h=harness();let hook=h.render();const original=photo();hook.select([original]);hook=h.render();
 const reserve=[],puts=[],completes=[];let failReservation=true,failComplete=true;
 globalThis.fetch=async(url,options)=>{
  if(url==='/api/v1/albums/a')return response({detail:{album:{version:7}}});
  if(url==='/api/v1/albums/a/uploads') {reserve.push(options);if(failReservation){failReservation=false;throw new TypeError('lost reply');}return response({uploads:[{client_file_id:JSON.parse(options.body).files[0].client_file_id,upload_id:'up',upload_url:'http://localhost/put',required_headers:{'If-None-Match':'*'}}]});}
  if(url==='http://localhost/put'){puts.push(options.body);return new Response(null,{status:200});}
  if(url.endsWith('/complete')){completes.push(options.body);if(failComplete){failComplete=false;throw new TypeError('lost completion');}return response({status:'ready'});}
  return response({status:'reserved'});
 };
 await hook.send();hook=h.render();assert.equal(hook.files[0],original);assert.equal(hook.locked,true);
 await hook.send();hook=h.render();await hook.send();
 assert.equal(decoded(),1);assert.equal(reserve[0].body,reserve[1].body);assert.equal(reserve[0].headers['Idempotency-Key'],reserve[1].headers['Idempotency-Key']);
 assert.equal(JSON.parse(reserve[0].body).files[0].preprocessing.original_width,100);
 assert.equal(puts.length,2);assert.equal(puts[0],puts[1]);assert.equal(puts[0].type,'image/webp');assert.equal(completes[0],completes[1]);h.cleanup();
});
test('private-memory reset aborts preparation before reservation and discards draft',async()=>{
 window.dispatchEvent(new Event('mori:logout'));
 browser();let finish;globalThis.createImageBitmap=()=>new Promise(resolve=>finish=resolve);
 const h=harness();let hook=h.render();hook.select([photo()]);hook=h.render();let requests=0;globalThis.fetch=async()=>{requests++;return response({detail:{album:{version:7}}});};
 const pending=hook.send();await new Promise(resolve=>setTimeout(resolve,0));window.dispatchEvent(new Event('mori:clear-private-memory'));finish({width:100,height:100,close(){}});await pending;
 assert.equal(requests,0);assert.equal(h.render().busy,false);h.cleanup();const next=harness();assert.equal(next.render().files.length,0);next.cleanup();
});
test.after(async()=>{await rm(temp,{recursive:true,force:true});});
