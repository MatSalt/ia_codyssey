import test from 'node:test';
import assert from 'node:assert/strict';
const flow = await import(process.argv[2]).catch(() => ({}));

test('bookshelf routes every public album state to its working screen', () => {
  assert.equal(typeof flow.albumPath, 'function');
  for (const [status,path] of [['draft','edit'],['processing','progress'],['action_required','progress'],['review_ready','review'],['published','view']]) {
    assert.equal(flow.albumPath({id:'a',status}), `/albums/a/${path}`);
  }
});
test('polling stops while hidden and at terminal or server-directed pause', () => {
  assert.equal(typeof flow.pollInterval, 'function');
  assert.equal(flow.pollInterval({run_status:'running',poll_after_ms:4200},true),4200);
  assert.equal(flow.pollInterval({run_status:'running',poll_after_ms:4200},false),false);
  assert.equal(flow.pollInterval({run_status:'succeeded',poll_after_ms:4200},true),false);
  assert.equal(flow.pollInterval({run_status:'cancelled',poll_after_ms:4200},true),false);
  assert.equal(flow.pollInterval({run_status:'action_required',poll_after_ms:null},true),false);
  assert.equal(flow.pollInterval({run_status:'action_required',poll_after_ms:3000},true),3000);
});
test('caption validation counts NFC code points and permits an empty user caption', () => {
  assert.equal(typeof flow.captionValue, 'function');
  assert.deepEqual(flow.captionValue(''),{text:'',count:0,valid:true});
  assert.deepEqual(flow.captionValue('가'.repeat(80)),{text:'가'.repeat(80),count:80,valid:true});
  assert.deepEqual(flow.captionValue('😀'.repeat(80)),{text:'😀'.repeat(80),count:80,valid:true});
  assert.equal(flow.captionValue('😀'.repeat(81)).valid,false);
});
test('response loss reuses the original key AND version, scoped by user and operation', () => {
  assert.equal(typeof flow.RequestIntents,'function');
  const intents=new flow.RequestIntents();
  const first=intents.get('alpha:a:generation',{expected_version:3});
  const retry=intents.get('alpha:a:generation',{expected_version:8});
  assert.deepEqual(retry,first);
  assert.equal(retry.body.expected_version,3);
  assert.notEqual(intents.get('beta:a:generation',{expected_version:3}).key,first.key);
  assert.notEqual(intents.get('alpha:a:publish',{expected_version:3}).key,first.key);
  intents.finish('alpha:a:generation');
  assert.notEqual(intents.get('alpha:a:generation',{expected_version:8}).key,first.key);
  intents.clear();
  assert.equal(intents.peek('alpha:a:publish'),undefined);
});
test('saving one page leaves another page version independent and protects edits during response', () => {
  assert.equal(typeof flow.savedDraft,'function');
  const a={text:'a edit',baseline:'a',version:4};
  const b={text:'b edit',baseline:'b',version:9};
  const next=flow.savedDraft(a,'a edit',{caption_text:'a edit',version:5});
  assert.deepEqual(next,{text:'a edit',baseline:'a edit',version:5});
  assert.equal(b.version,9);
  assert.equal(flow.savedDraft({...a,text:'new typing'},'a edit',{caption_text:'a edit',version:5}).text,'new typing');
});
test('viewer requests only current and next missing or expired URLs and preserves page ID', () => {
  assert.equal(typeof flow.neededMedia,'function');
  const pages=[1,2,3,4].map(id=>({id:String(id),image:{asset_id:`asset-${id}`}}));
  const access=[{asset_id:'asset-1',url:'/private/1',expires_at:'2030-01-01T00:05:00Z'}];
  assert.deepEqual(flow.neededMedia(pages,0,access,Date.parse('2030-01-01T00:00:00Z')),['asset-2']);
  assert.deepEqual(flow.neededMedia(pages,1,access,Date.parse('2030-01-01T00:00:00Z')),['asset-2','asset-3']);
  assert.deepEqual(flow.neededMedia(pages,0,access,Date.parse('2030-01-01T00:05:00Z')),['asset-1','asset-2']);
  assert.equal(flow.currentPageIndex(pages,'3'),2);
  assert.equal(flow.currentPageIndex(pages,'removed'),0);
});
test('touch navigation ignores vertical gestures and clamps at the book edges', () => {
  assert.equal(typeof flow.swipeOffset,'function');
  assert.equal(flow.swipeOffset(120,5),-1);
  assert.equal(flow.swipeOffset(-100,10),1);
  assert.equal(flow.swipeOffset(15,2),0);
  assert.equal(flow.swipeOffset(70,110),0);
  assert.equal(flow.nextPageIndex(0,-1,4),0);
  assert.equal(flow.nextPageIndex(3,1,4),3);
});
test('rapid page navigation requests the newly needed media after an in-flight renewal', async()=>{
 assert.equal(typeof flow.MediaRenewals,'function');
 let required=['a','b'];let finishFirst;const received=[];const sent=[];
 const gate=new flow.MediaRenewals();
 const first=gate.run(()=>required,ids=>{sent.push(ids);return new Promise(resolve=>{finishFirst=()=>{required=['c','d'];resolve(ids);};});},value=>received.push(value));
 required=['c','d'];
 await gate.run(()=>required,async ids=>{sent.push(ids);required=[];return ids;},value=>received.push(value));
 finishFirst();await first;
 assert.deepEqual(sent,[['a','b'],['c','d']]);
 assert.deepEqual(received,[['a','b'],['c','d']]);
});
test('viewer arrows work without a focused photo but preserve text editing and modified shortcuts',()=>{
 assert.equal(typeof flow.keyboardOffset,'function');
 assert.equal(flow.keyboardOffset('ArrowLeft',false,false),-1);
 assert.equal(flow.keyboardOffset('ArrowRight',false,false),1);
 assert.equal(flow.keyboardOffset('ArrowRight',false,true),0);
 assert.equal(flow.keyboardOffset('ArrowLeft',true,false),0);
 assert.equal(flow.keyboardOffset('Enter',false,false),0);
});
