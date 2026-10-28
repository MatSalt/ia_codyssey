import test from 'node:test';
import assert from 'node:assert/strict';
const recovery=await import(process.argv[2]).catch(()=>({}));
test('expired-session captions restore only for the same user and preserve page expected_version',()=>{
 assert.equal(typeof recovery.ReviewDrafts,'function');
 const vault=new recovery.ReviewDrafts();vault.selectOwner('alpha');
 vault.remember('alpha','album',{a:{text:'내 미저장 입력',baseline:'서버 글귀',version:7,saving:true},b:{text:'저장됨',baseline:'저장됨',version:2}});
 assert.deepEqual(vault.restore('alpha','album'),{a:{text:'내 미저장 입력',baseline:'서버 글귀',version:7}});
 const restored=vault.restore('alpha','album');restored.a.text='changed outside';
 assert.equal(vault.restore('alpha','album').a.text,'내 미저장 입력');
 assert.deepEqual(vault.restore('beta','album'),{});
});
test('another user login evicts old captions and ignores late writes from the old screen',()=>{
 assert.equal(typeof recovery.ReviewDrafts,'function');
 const vault=new recovery.ReviewDrafts();vault.selectOwner('alpha');
 vault.remember('alpha','album',{a:{text:'private alpha',baseline:'',version:1}});
 vault.selectOwner('beta');
 vault.remember('alpha','album',{a:{text:'late private alpha',baseline:'',version:1}});
 assert.deepEqual(vault.restore('beta','album'),{});
 vault.selectOwner('alpha');assert.deepEqual(vault.restore('alpha','album'),{});
});
test('confirmed navigation discard and explicit logout erase recoverable captions',()=>{
 assert.equal(typeof recovery.ReviewDrafts,'function');
 const vault=new recovery.ReviewDrafts();vault.selectOwner('alpha');
 vault.remember('alpha','album',{a:{text:'private',baseline:'',version:1}});
 vault.forget('alpha','album');assert.deepEqual(vault.restore('alpha','album'),{});
 vault.remember('alpha','album',{a:{text:'private',baseline:'',version:1}});
 vault.clear();vault.remember('alpha','album',{a:{text:'stale',baseline:'',version:1}});
 vault.selectOwner('alpha');assert.deepEqual(vault.restore('alpha','album'),{});
});
