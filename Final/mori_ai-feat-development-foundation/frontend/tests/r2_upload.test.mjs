import test from 'node:test';
import assert from 'node:assert/strict';
const {completionBody,putFile,uploadStep}=await import(process.argv[2]);
const headers={'Content-Type':'image/png','If-None-Match':'*'};
test('R2 hashes original File once while local does not read it',async()=>{
 let reads=0; const file=new File(['abcd'],'test.png'); const original=file.arrayBuffer.bind(file);
 file.arrayBuffer=()=>{reads++;return original();};
 assert.deepEqual(await completionBody(file,{}),{}); assert.equal(reads,0);
 const expected={sha256:'88d4266fd4e6338d13b845fcf289579d209c897823b9217da3e161936f031589'};
 assert.deepEqual(await completionBody(file,headers),expected);
 assert.deepEqual(await completionBody(file,headers),expected); assert.equal(reads,1);
});
test('only conditional R2 412 proceeds to server verification; other HTTP failures throw',async()=>{
 const original=globalThis.fetch;
 try {
  globalThis.fetch=async()=>new Response(null,{status:412});
  await putFile('https://r2.invalid/',new File(['abcd'],'a'),headers,new AbortController().signal);
  await assert.rejects(putFile('/local',new File(['abcd'],'a'),{},new AbortController().signal));
  globalThis.fetch=async()=>new Response(null,{status:503});
  await assert.rejects(putFile('https://r2.invalid/',new File(['abcd'],'a'),headers,new AbortController().signal));
 }finally{globalThis.fetch=original;}
});
test('lost PUT response retry preserves original bytes, URL and headers',async()=>{
 const original=globalThis.fetch; const file=new File(['abcd'],'a');const calls=[];
 try {
  globalThis.fetch=async(url,init)=>{calls.push([url,init]);if(calls.length===1)throw new TypeError('network lost');return new Response(null,{status:412});};
  const send=()=>putFile('https://r2.invalid/fixed',file,headers,new AbortController().signal);
  assert.equal(await send(),'verify');await send();
  assert.equal(calls[0][0],calls[1][0]);assert.equal(calls[1][1].body,file);
  assert.deepEqual(calls[1][1].headers,headers);assert.equal(calls[1][1].credentials,'same-origin');
  assert.equal('Content-Length' in calls[1][1].headers,false);
 }finally{globalThis.fetch=original;}
});
test('hash rejects oversized input before allocating and unavailable crypto',async()=>{
 await assert.rejects(completionBody({size:20971521,arrayBuffer(){throw Error('allocated');}},headers),/20/);
 const original=globalThis.crypto;
 try {Object.defineProperty(globalThis,'crypto',{value:undefined,configurable:true});await assert.rejects(completionBody(new File(['abcd'],'a'),headers),/SHA/);}
 finally{Object.defineProperty(globalThis,'crypto',{value:original,configurable:true});}
});

function scenario(required=headers) {
 const file=new File(['abcd'],'original.png');
 const upload={upload_id:'reservation-1',upload_url:'https://r2.invalid/fixed',required_headers:required};
 const state={put:new Set(),complete:new Set()};
 const controller=new AbortController();
 const calls=[];
 let stored=false;
 const run=()=>uploadStep(upload,file,state,controller.signal,required,async()=>({status:'reserved'}),async(body)=>{
  calls.push(['complete',body]);
  if(!stored)throw Object.assign(new Error('UPLOAD_NOT_READY'),{status:422});
  assert.deepEqual(body,required['If-None-Match']==='*'?{sha256:'88d4266fd4e6338d13b845fcf289579d209c897823b9217da3e161936f031589'}:{});
 });
 return {file,upload,state,controller,calls,run,store(){stored=true;}};
}
for(const failure of [new TypeError('CORS response unavailable'),new DOMException('timed out','TimeoutError')]) {
 test(`stored PUT with ${failure.name} is confirmed by complete SHA`,async()=>{
  const original=globalThis.fetch;const s=scenario();
  try {
   globalThis.fetch=async(url,init)=>{s.calls.push(['put',url,init.body]);s.store();throw failure;};
   await s.run();
   assert.deepEqual(s.calls.map(c=>c[0]),['put','complete']);
   assert.equal(s.calls[0][2],s.file);assert.equal(s.state.complete.has('reservation-1'),true);
   await s.run();assert.equal(s.calls.length,2);
  }finally{globalThis.fetch=original;}
 });
}
for(const failure of ['network','412']) {
 test(`unconfirmed ${failure} retries actual PUT with the original reservation and File`,async()=>{
  const original=globalThis.fetch;const s=scenario();let attempts=0;
  try {
   globalThis.fetch=async(url,init)=>{
    s.calls.push(['put',url,init.body]);attempts++;
    if(attempts===1){if(failure==='network')throw new TypeError('not sent');return new Response(null,{status:412});}
    s.store();return new Response(null,{status:200});
   };
   await assert.rejects(s.run(),/UPLOAD_NOT_READY/);
   assert.equal(s.state.put.size,0);assert.equal(s.state.complete.size,0);
   await s.run();assert.equal(attempts,2);
   assert.deepEqual(s.calls.map(c=>c[0]),['put','complete','put','complete']);
   assert.equal(s.calls[0][1],s.calls[2][1]);assert.equal(s.calls[0][2],s.calls[2][2]);
   assert.equal(s.state.complete.has('reservation-1'),true);
  }finally{globalThis.fetch=original;}
 });
}
test('checksum conflict never marks an upload complete, including a previous PUT marker',async()=>{
 const original=globalThis.fetch;const s=scenario();let checks=0;
 try {
  globalThis.fetch=async()=>{throw new TypeError('lost response');};
  s.state.put.add('reservation-1');
  await assert.rejects(uploadStep(s.upload,s.file,s.state,s.controller.signal,headers,async()=>({status:'validating'}),async()=>{checks++;throw new Error('409 STATE_CONFLICT');}),/409/);
  assert.equal(checks,1);assert.equal(s.state.put.size,0);assert.equal(s.state.complete.size,0);
 }finally{globalThis.fetch=original;}
});
test('user abort skips completion even when fetch reports TypeError',async()=>{
 const original=globalThis.fetch;const s=scenario();
 try {
  globalThis.fetch=async()=>{s.controller.abort();throw new TypeError('aborted');};
  await assert.rejects(s.run());assert.equal(s.calls.length,0);assert.equal(s.state.complete.size,0);
 }finally{globalThis.fetch=original;}
});
test('local network errors do not attempt completion',async()=>{
 const original=globalThis.fetch;const s=scenario({'Content-Type':'image/png'});
 try {
  globalThis.fetch=async()=>{throw new TypeError('network');};
  await assert.rejects(s.run(),/network/);assert.equal(s.calls.length,0);
 }finally{globalThis.fetch=original;}
});

test('validating retry skips PUT but still confirms the original hash',async()=>{
 const original=globalThis.fetch;const s=scenario();let checks=0;
 try {
  globalThis.fetch=async()=>{throw new Error('unexpected PUT');};
  await uploadStep(s.upload,s.file,s.state,s.controller.signal,headers,async()=>({status:'validating'}),async(body)=>{
   checks++;assert.deepEqual(body,{sha256:'88d4266fd4e6338d13b845fcf289579d209c897823b9217da3e161936f031589'});
  });
  assert.equal(checks,1);assert.equal(s.state.complete.size,1);
 }finally{globalThis.fetch=original;}
});
