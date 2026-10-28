import test from 'node:test';
import assert from 'node:assert/strict';
const oauth = await import(process.argv[2]);
const id = '12345678-1234-1234-1234-123456789abc';
test('OAuth navigates through same-origin start with only allowed return paths', () => {
  for (const provider of ['google', 'kakao']) {
    for (const path of ['/goods', '/designs', `/designs/${id}`, '/albums', ...['edit','progress','review','view'].map(view => `/albums/${id}/${view}`)]) {
      assert.equal(oauth.oauthLoginUrl(provider, path), `/api/v1/auth/${provider}/start?return_to=${encodeURIComponent(path)}`);
    }
  }
});
test('untrusted return locations fall back to goods', () => {
  for (const path of ['https://evil.test','//evil.test','/albums?token=secret','/albums#secret',`/albums/${id}/edit?x=1`, '/albums/not-a-uuid/view', '/login', '/albums/new', '/albums/../login', '/albums/', `/albums/${id}/view\n`]) {
    assert.equal(oauth.oauthLoginUrl('google', path), '/api/v1/auth/google/start?return_to=%2Fgoods');
  }
  assert.throws(() => oauth.oauthLoginUrl('unknown', '/albums'));
});
test('callback errors display only public enum messages, never supplied details', () => {
  assert.match(oauth.oauthErrorMessage('?auth_error=failed&token=secret'), /로그인/);
  assert.match(oauth.oauthErrorMessage('?auth_error=cancelled'), /취소/);
  for (const search of ['', '?auth_error=secret', '?error_description=secret', '?auth_error=failed%3Cscript%3E']) assert.equal(oauth.oauthErrorMessage(search), '');
});
test('provider configuration defaults closed and accepts only known unique providers', () => {
  for (const value of [undefined, null, {}, 'google']) assert.deepEqual(oauth.oauthProviders(value), []);
  assert.deepEqual(oauth.oauthProviders(['google', 'unknown', 'kakao', 'google']), ['google', 'kakao']);
});
if (process.argv[3]) {
  const {createElement} = await import('react');
  const {renderToStaticMarkup} = await import('react-dom/server');
  const {OAuthLoginOptions} = await import(process.argv[3]);
  const render = props => renderToStaticMarkup(createElement(OAuthLoginOptions, {providers:[], pending:false, failed:false, retry:()=>{}, returnTo:'/albums', ...props}));
  test('login screen exposes only configured provider navigation', () => {
    assert.doesNotMatch(render({}), /href=/);
    const html = render({providers:['google','unknown']});
    assert.match(html, /Google로 로그인/);
    assert.match(html, /href="\/api\/v1\/auth\/google\/start\?return_to=%2Falbums"/);
    assert.doesNotMatch(html, /Kakao로 로그인|unknown/);
    assert.match(render({providers:['kakao']}), /Kakao로 로그인/);
  });
  test('login configuration has loading and safe retry states', () => {
    assert.match(render({pending:true}), /role="status"/);
    const failed = render({failed:true, providers:['google']});
    assert.match(failed, /role="alert"/);
    assert.match(failed, /다시 시도/);
    assert.doesNotMatch(failed, /href=/);
  });
}
