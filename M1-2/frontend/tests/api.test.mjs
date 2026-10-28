import test from 'node:test';
import assert from 'node:assert/strict';
const { request } = await import('../js/api.js');
const config = () => { globalThis.window = { APP_CONFIG: { API_BASE_URL: 'https://api.test/' } }; };
test('204 deletion resolves null and preserves request method', async () => {
 config(); globalThis.fetch = async (url, options) => { assert.equal(url, 'https://api.test/api/data/2026-01-01'); assert.equal(options.method, 'DELETE'); return new Response(null, {status:204}); };
 assert.equal(await request('/api/data/2026-01-01', {method:'DELETE'}), null);
});
test('validation error exposes readable detail and status', async () => {
 config(); globalThis.fetch = async () => new Response(JSON.stringify({detail:[{loc:['body','value'],msg:'Input should be a valid integer'}]}), {status:422});
 await assert.rejects(request('/api/data'), e => e.status === 422 && Array.isArray(e.detail) && /value.*valid integer/.test(e.message));
});
test('service error detail and network errors remain understandable', async () => {
 config(); globalThis.fetch = async () => new Response(JSON.stringify({detail:'저장소에 연결할 수 없습니다.'}), {status:503});
 await assert.rejects(request('/api/data'), /저장소/);
 globalThis.fetch = async () => { throw new TypeError('Failed to fetch'); };
 await assert.rejects(request('/api/data'), /연결/);
});
test('missing config fails before requesting', async () => {
 globalThis.window = {}; globalThis.fetch = async () => { assert.fail('must not fetch'); };
 await assert.rejects(request('/api/data'), /API_BASE_URL/);
});
test('JSON body serialized and sixty second timeout aborts request', async () => {
 config(); const original = globalThis.setTimeout; const clear = globalThis.clearTimeout;
 globalThis.setTimeout = (fn, ms) => { assert.equal(ms,60000); queueMicrotask(fn); return 1; }; globalThis.clearTimeout = () => {};
 globalThis.fetch = async (url, options) => { assert.equal(options.body,'{"value":2}'); assert.equal(options.headers.get('Content-Type'),'application/json'); await new Promise(resolve => queueMicrotask(resolve)); if (options.signal.aborted) throw new DOMException('Aborted','AbortError'); };
 try { await assert.rejects(request('/api/data',{method:'POST',body:{value:2}}), /60초/); } finally {globalThis.setTimeout=original; globalThis.clearTimeout=clear;}
});
