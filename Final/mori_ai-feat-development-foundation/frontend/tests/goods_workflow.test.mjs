import test from 'node:test';import assert from 'node:assert/strict';import {build} from 'esbuild';
await build({entryPoints:['src/features/goods/workflow.ts'],bundle:true,platform:'node',format:'esm',outfile:'goods-workflow-check.mjs'});
const {replacePhoto,discardMessage}=await import('../goods-workflow-check.mjs');
test('cancel replacement never uploads or discards existing work',async()=>{
 const calls=[];const result=await replacePhoto(true,()=>false,async()=>{calls.push('upload');return 'new';},async()=>calls.push('discard'));
 assert.equal(result,null);assert.deepEqual(calls,[]);
});
test('invalid replacement preserves existing work; success validates before discard',async()=>{
 const calls=[];await assert.rejects(()=>replacePhoto(true,()=>true,async()=>{throw Error('invalid');},async()=>calls.push('discard')));assert.deepEqual(calls,[]);
 assert.equal(await replacePhoto(true,()=>true,async()=>{calls.push('validated');return 'new';},async()=>calls.push('discard')),'new');assert.deepEqual(calls,['validated','discard']);assert.match(discardMessage,/저장되지/);
});
test('failed first generation retries from the reference, never from failed revision',async()=>{
 const workflow=await import('../goods-workflow-check.mjs');
 assert.equal(workflow.generationParent([{id:'bad',status:'failed'}],'bad'),null);
 assert.equal(workflow.generationParent([{id:'ok',status:'ready'}],'ok'),'ok');
 assert.notEqual(workflow.workspaceKey('u','visit1'),workflow.workspaceKey('u','visit2'));
});
