import test from 'node:test';
import assert from 'node:assert/strict';
const guard=await import(process.argv[2]).catch(()=>({}));
test('unsaved text blocks browser unload and a declined logout without prompting on unload',()=>{
 assert.equal(typeof guard.installUnsavedGuard,'function');
 const target=new EventTarget();let prompts=0;
 const dispose=guard.installUnsavedGuard(target,()=>{prompts++;return false;});
 const unload=new Event('beforeunload',{cancelable:true});
 assert.equal(target.dispatchEvent(unload),false);assert.equal(prompts,0);
 assert.equal(target.dispatchEvent(new Event('mori:before-logout',{cancelable:true})),false);
 assert.equal(prompts,1);dispose();
 assert.equal(target.dispatchEvent(new Event('beforeunload',{cancelable:true})),true);
 assert.equal(target.dispatchEvent(new Event('mori:before-logout',{cancelable:true})),true);
});
test('explicit discard permits logout while preserving the guard for a later edit',()=>{
 assert.equal(typeof guard.installUnsavedGuard,'function');
 const target=new EventTarget();let agreed=true;
 const dispose=guard.installUnsavedGuard(target,()=>agreed);
 assert.equal(target.dispatchEvent(new Event('mori:before-logout',{cancelable:true})),true);
 agreed=false;
 assert.equal(target.dispatchEvent(new Event('mori:before-logout',{cancelable:true})),false);
 dispose();
});
