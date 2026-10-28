import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, readFile, readdir, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const builder = fileURLToPath(new URL('../scripts/build.mjs', import.meta.url));
async function fixture(t) {
  const root = await mkdtemp(join(tmpdir(), 'story-build-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  await mkdir(join(root, 'scripts'));
  await mkdir(join(root, 'js'));
  // Execute the same builder against a complete isolated source tree.
  await writeFile(join(root, 'scripts/build.mjs'), await readFile(builder));
  for (const name of ['index.html', 'styles.css', 'js/app.js']) await writeFile(join(root, name), `fixture ${name}`);
  for (const name of ['.env', 'private.csv', 'config.example.js', 'service-account.json']) await writeFile(join(root, name), 'SECRET_SENTINEL');
  await mkdir(join(root, 'dist'));
  await writeFile(join(root, 'dist/stale.txt'), 'stale');
  return root;
}
function build(root, url) {
  const env = { ...process.env, OPENAI_API_KEY: 'FAKE_PRIVATE_KEY' };
  delete env.API_BASE_URL;
  if (url !== undefined) env.API_BASE_URL = url;
  return spawnSync(process.execPath, [join(root, 'scripts/build.mjs')], { env, encoding: 'utf8' });
}
test('build publishes only frontend assets and JSON-safe public configuration', async t => {
  const root = await fixture(t);
  const url = 'https://api.example.test/path?q="quoted"&x=\\value';
  assert.equal(build(root, url).status, 0);
  assert.deepEqual((await readdir(join(root, 'dist'))).sort(), ['config.js', 'index.html', 'js', 'styles.css']);
  assert.equal(await readFile(join(root, 'dist/js/app.js'), 'utf8'), 'fixture js/app.js');
  assert.equal(await readFile(join(root, 'dist/index.html'), 'utf8'), 'fixture index.html');
  assert.equal(await readFile(join(root, 'dist/styles.css'), 'utf8'), 'fixture styles.css');
  const config = await readFile(join(root, 'dist/config.js'), 'utf8');
  const context = { window: {} };
  vm.runInNewContext(config, context);
  assert.deepEqual(Object.keys(context.window.APP_CONFIG), ['API_BASE_URL']);
  assert.equal(context.window.APP_CONFIG.API_BASE_URL, url);
  assert.ok(!config.includes('FAKE_PRIVATE_KEY'));
});
for (const url of [undefined, '', 'not-a-url', 'ftp://api.example.test', 'javascript:alert(1)', 'https://user:password@api.example.test']) {
  test(`build rejects missing or unsafe API URL: ${url}`, async t => {
    const root = await fixture(t);
    const result = build(root, url);
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /API_BASE_URL/);
    assert.equal(await readFile(join(root, 'dist/stale.txt'), 'utf8'), 'stale');
  });
}
