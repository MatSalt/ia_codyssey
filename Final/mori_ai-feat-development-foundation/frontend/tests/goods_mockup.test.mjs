import test from 'node:test';
import assert from 'node:assert/strict';
const {createPreviewController, previewKey}=await import(process.argv[2]||'../src/features/goods/mockup/preview.ts');
const input=(src='a',x=.5)=>({src,product:'keyring',placement:{holeX:x,holeY:0,widthMm:50}});
function setup(){const pending=[],states=[];const controller=createPreviewController((value,signal)=>new Promise((resolve,reject)=>pending.push({value,signal,resolve,reject})),s=>states.push(s));return {controller,pending,states};}
test('new artwork or hole invalidates old ready result immediately',async()=>{
 const {controller,pending,states}=setup();const first=controller.update(input());pending[0].resolve('first');await first;
 assert.equal(states.at(-1).status,'ready');const next=controller.update(input('a',.2));
 assert.equal(states.at(-1).status,'pending');assert.equal('result' in states.at(-1),false);
 pending[1].resolve('second');await next;assert.equal(states.at(-1).result,'second');assert.equal(states.at(-1).key,previewKey(input('a',.2)));
});
test('late old success cannot overwrite newer artwork',async()=>{
 const {controller,pending,states}=setup();const a=controller.update(input('a'));const b=controller.update(input('b'));
 assert.equal(pending[0].signal.aborted,true);pending[1].resolve('b');await b;pending[0].resolve('a');await a;
 assert.equal(states.at(-1).result,'b');assert.equal(states.filter(s=>s.status==='ready').length,1);
});
test('late failure is ignored but current failure clears result and can retry',async()=>{
 const {controller,pending,states}=setup();const a=controller.update(input('a'));const b=controller.update(input('b'));
 pending[0].reject(Error('old private url'));await a;assert.equal(states.at(-1).status,'pending');
 pending[1].reject(Error('current private url'));await b;assert.equal(states.at(-1).status,'error');assert.equal('result' in states.at(-1),false);assert.equal(JSON.stringify(states).includes('private url'),false);
 const c=controller.update(input('b'));pending[2].resolve('retry');await c;assert.equal(states.at(-1).result,'retry');
});
test('disposal aborts load and never publishes late result',async()=>{
 const {controller,pending,states}=setup();const p=controller.update(input());controller.dispose();const count=states.length;
 assert.equal(pending[0].signal.aborted,true);pending[0].resolve('late');await p;assert.equal(states.length,count);
 await controller.update(input('b'));assert.equal(pending.length,1);
});
test('preview identity includes product, source, width and both coordinates',()=>{
 const a=input();const key=previewKey(a);
 for(const b of [{...a,src:'b'},{...a,product:'magnet'},{...a,placement:{...a.placement,holeY:.4}},{...a,placement:{...a.placement,widthMm:60}}])assert.notEqual(previewKey(b),key);
});
