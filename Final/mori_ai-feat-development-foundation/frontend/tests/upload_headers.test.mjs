import test from 'node:test';
import assert from 'node:assert/strict';

const client = await import(process.argv[2]);
const origin = 'http://127.0.0.1:8000';

test('private local PUT uses the current session CSRF without mutating required headers', () => {
  const required = {'Content-Type': 'image/heic'};
  client.setCsrf('new-session-csrf');
  assert.deepEqual(client.uploadHeaders('/api/v1/private/uploads/id?signature=test', required, origin),
    {...required, 'X-CSRF-Token': 'new-session-csrf'});
  assert.deepEqual(required, {'Content-Type': 'image/heic'});
});

test('current session CSRF never goes to an external storage origin', () => {
  client.setCsrf('private-session-csrf');
  const required = {'Content-Type': 'image/png', 'x-provider-header': 'required'};
  assert.deepEqual(client.uploadHeaders('https://storage.example/upload', required, origin), required);
});

test('logout clears PUT authentication headers and non-API URLs get no token', () => {
  client.setCsrf('session-csrf');
  assert.deepEqual(client.uploadHeaders('/ordinary-upload', {}, origin), {});
  client.setCsrf();
  assert.deepEqual(client.uploadHeaders('/api/v1/private/uploads/id', {}, origin), {});
});
