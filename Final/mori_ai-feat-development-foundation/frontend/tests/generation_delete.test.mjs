import test from 'node:test';
import assert from 'node:assert/strict';
const albums=await import(process.argv[2]).catch(()=>({}));
globalThis.window=new EventTarget();
const detail={detail:{album:{id:'album-a',title:'나의 사진첩',status:'published',version:17,page_count:0,cover:null,created_at:'2026-10-16T00:00:00Z',updated_at:'2026-10-16T01:00:00Z',published_at:'2026-10-16T01:00:00Z'},pages:[],order_mode:'date',active_run_id:null},media_access:[]};
test('bookshelf deletion reads the latest album version instead of using the displayed stale version',async()=>{
 assert.equal(typeof albums.removeAlbum,'function');
 const oldFetch=globalThis.fetch;const calls=[];
 globalThis.fetch=async(url,options)=>{calls.push([url,options.method]);return new Response(JSON.stringify({data:options.method==='GET'?detail:{album_id:'album-a',status:'deleted'}}),{status:options.method==='GET'?200:202});};
 try{await albums.removeAlbum('album-a',new AbortController().signal);
  assert.deepEqual(calls,[['/api/v1/albums/album-a','GET'],['/api/v1/albums/album-a?expected_version=17','DELETE']]);
 }finally{globalThis.fetch=oldFetch;}
});
test('a refused delete remains a failure instead of displaying fake success',async()=>{
 assert.equal(typeof albums.removeAlbum,'function');
 const oldFetch=globalThis.fetch;
 globalThis.fetch=async(url,options)=>options.method==='GET'?new Response(JSON.stringify({data:detail}),{status:200}):new Response(JSON.stringify({error:{code:'VERSION_CONFLICT',details:{current_version:18}}}),{status:409});
 try{await assert.rejects(albums.removeAlbum('album-a',new AbortController().signal),error=>error.status===409&&error.details.current_version===18);}finally{globalThis.fetch=oldFetch;}
});

for(const kind of ['network','timeout','server'])test(`ambiguous ${kind} delete confirms disappearance without repeating DELETE`,async()=>{
 const oldFetch=globalThis.fetch;const calls=[];
 globalThis.fetch=async(url,options)=>{
  calls.push(options.method);
  if(options.method==='DELETE'){
   if(kind==='network')throw new TypeError('response lost');
   if(kind==='timeout')throw new DOMException('response lost','TimeoutError');
   return new Response(JSON.stringify({error:{code:'TEMPORARILY_UNAVAILABLE'}}),{status:503});
  }
  return new Response(JSON.stringify(calls.length===1?{data:detail}:{error:{code:'RESOURCE_NOT_FOUND'}}),{status:calls.length===1?200:404});
 };
 try{await albums.removeAlbum('album-a',new AbortController().signal);assert.deepEqual(calls,['GET','DELETE','GET']);}
 finally{globalThis.fetch=oldFetch;}
});
test('ambiguous deletion never reports success while the album still exists',async()=>{
 const oldFetch=globalThis.fetch;const lost=new TypeError('response lost');const calls=[];
 globalThis.fetch=async(url,options)=>{calls.push(options.method);if(options.method==='DELETE')throw lost;return new Response(JSON.stringify({data:detail}),{status:200});};
 try{await assert.rejects(albums.removeAlbum('album-a',new AbortController().signal),error=>error===lost);assert.deepEqual(calls,['GET','DELETE','GET']);}
 finally{globalThis.fetch=oldFetch;}
});
test('losing authentication during confirmation never proves deletion',async()=>{
 const oldFetch=globalThis.fetch;const calls=[];const lost=new TypeError('response lost');
 globalThis.fetch=async(url,options)=>{calls.push(options.method);if(options.method==='DELETE')throw lost;return new Response(JSON.stringify(calls.length===1?{data:detail}:{error:{code:'AUTH_REQUIRED'}}),{status:calls.length===1?200:401});};
 try{await assert.rejects(albums.removeAlbum('album-a',new AbortController().signal));assert.deepEqual(calls,['GET','DELETE','GET']);}
 finally{globalThis.fetch=oldFetch;}
});
