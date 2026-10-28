import test from 'node:test';
import assert from 'node:assert/strict';
import { initConversations } from '../js/conversations.js';

// Small native-event DOM boundary: production conversation logic remains intact.
class Element extends EventTarget {
  children = [];
  disabled = false;
  textContent = '';
  className = '';
  classList = { toggle() {} };
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  setAttribute() {}
  scrollIntoView() {}
  click() { if (!this.disabled) this.dispatchEvent(new Event('click')); }
}
const settle = () => new Promise(resolve => setImmediate(resolve));
const deferred = () => { let resolve; const promise = new Promise(done => {resolve = done;}); return {promise,resolve}; };
async function scenario(run) {
  const priorDocument = globalThis.document, priorWindow = globalThis.window;
  globalThis.document = {createElement: () => new Element()};
  globalThis.window = {confirm: () => true};
  try {
    const nodes = Object.fromEntries(['history-list','history-status','history-refresh','chat'].map(id => [`#${id}`,new Element()]));
    const root = new Element(); root.querySelector = selector => nodes[selector];
    const row = {id:'one',title:'합성 대화',updated_at:'2026-01-01T00:00:00Z'};
    const deletion = deferred(), detail = deferred();
    const selected = []; let gets = 0;
    root.addEventListener('conversation-selected', event => selected.push(event.detail.id));
    initConversations(root, async (path, options = {}) => {
      if (options.method === 'DELETE') return deletion.promise;
      if (path === '/api/conversations') return {items:[row]};
      gets++; return detail.promise;
    });
    await settle();
    const buttons = () => nodes['#history-list'].children[0]?.children;
    await run({root,nodes,buttons,deletion,detail,selected,row,get gets() {return gets;}});
  } finally {globalThis.document = priorDocument; globalThis.window = priorWindow;}
}

test('deleting conversation cannot be opened after list refresh', async () => scenario(async state => {
  state.buttons()[1].click();
  assert.equal(state.buttons()[0].disabled,true);
  const oldRow = state.nodes['#history-list'].children[0];
  state.nodes['#history-refresh'].click();
  await settle();
  assert.notEqual(state.nodes['#history-list'].children[0],oldRow);
  assert.equal(state.buttons()[0].disabled,true);
  state.buttons()[0].click();
  assert.equal(state.gets,0);
}));

test('DELETE success prevents late detail response restoring deleted conversation', async () => scenario(async state => {
  state.buttons()[1].click();
  // A queued activation must remain harmless even when the button is disabled.
  state.buttons()[0].dispatchEvent(new Event('click'));
  state.deletion.resolve(null);
  await settle();
  state.detail.resolve({...state.row,messages:[]});
  await settle();
  assert.deepEqual(state.selected,[]);
}));

test('a detail request started before deletion cannot restore after DELETE succeeds', async () => scenario(async state => {
  state.buttons()[0].click();
  assert.equal(state.gets,1);
  state.buttons()[1].click();
  state.deletion.resolve(null);
  await settle();
  state.detail.resolve({...state.row,messages:[]});
  await settle();
  assert.deepEqual(state.selected,[]);
}));
