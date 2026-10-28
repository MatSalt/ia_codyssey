import test from 'node:test';
import assert from 'node:assert/strict';
import {QueryClient, QueryObserver} from '@tanstack/query-core';

const session = await import(process.argv[2]);

test('logout clears private data and updates the mounted session observer', async () => {
  const cache = new QueryClient();
  cache.setQueryData(['session'], {user: {id: 'alpha'}});
  cache.setQueryData(['albums', 'alpha'], [{id: 'private-album'}]);
  cache.setQueryData(['client-config', 'alpha'], {auth_providers: ['google']});
  cache.setQueryData(['dev-config'], {dev_auth_enabled: true});
  const observer = new QueryObserver(cache, {queryKey: ['session'], enabled: false});
  const unsubscribe = observer.subscribe(() => {});
  await session.resetSession(cache);
  assert.equal(observer.getCurrentResult().data, null);
  assert.equal(cache.getQueryData(['albums', 'alpha']), undefined);
  assert.equal(cache.getQueryData(['client-config', 'alpha']), undefined);
  assert.deepEqual(cache.getQueryData(['dev-config']), {dev_auth_enabled: true});
  cache.setQueryData(['session'], {user: {id: 'beta'}});
  assert.equal(observer.getCurrentResult().data.user.id, 'beta');
  unsubscribe(); cache.clear();
});

test('logout cancels pending private queries before removing them', async () => {
  const cache = new QueryClient();
  let cancelled = false;
  const pending = cache.fetchQuery({queryKey: ['album', 'alpha'], retry: false,
    queryFn: ({signal}) => new Promise((_, reject) => {
      signal.addEventListener('abort', () => {cancelled = true; reject(new Error('cancelled'));});
    })}).catch(() => undefined);
  await session.resetSession(cache);
  await pending;
  assert.equal(cancelled, true);
  assert.equal(cache.getQueryData(['album', 'alpha']), undefined);
  assert.equal(cache.getQueryData(['session']), null);
  cache.clear();
});

test('an initial 401 does not cancel the public development login configuration', async () => {
  const cache = new QueryClient();
  let cancelled = false;
  let finish;
  const pending = cache.fetchQuery({queryKey: ['dev-config'], retry: false,
    queryFn: ({signal}) => new Promise(resolve => {
      finish = resolve;
      signal.addEventListener('abort', () => {cancelled = true;});
    })}).catch(() => undefined);
  await session.resetSession(cache);
  finish({dev_auth_enabled: true});
  await pending;
  assert.equal(cancelled, false);
  assert.deepEqual(cache.getQueryData(['dev-config']), {dev_auth_enabled: true});
  cache.clear();
});

test('session expiry preserves the pending public OAuth provider configuration', async () => {
  const cache = new QueryClient();
  let cancelled = false;
  let finish;
  const pending = cache.fetchQuery({queryKey: ['client-config'], retry: false,
    queryFn: ({signal}) => new Promise(resolve => {
      finish = resolve;
      signal.addEventListener('abort', () => {cancelled = true;});
    })}).catch(() => undefined);
  await session.resetSession(cache, 'expired');
  finish({auth_providers: ['google']});
  await pending;
  assert.equal(cancelled, false);
  assert.deepEqual(cache.getQueryData(['client-config']), {auth_providers: ['google']});
  cache.clear();
});
