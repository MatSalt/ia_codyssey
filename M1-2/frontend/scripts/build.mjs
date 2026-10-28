import { cp, mkdir, rm, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const source = dirname(dirname(fileURLToPath(import.meta.url)));
const output = join(source, 'dist');
const apiBaseUrl = process.env.API_BASE_URL;
try {
  if (!apiBaseUrl || apiBaseUrl !== apiBaseUrl.trim()) throw new Error();
  const url = new URL(apiBaseUrl);
  if (!['http:', 'https:'].includes(url.protocol) || !url.hostname || url.username || url.password) throw new Error();
} catch {
  console.error('API_BASE_URL must be an absolute http(s) URL without credentials.');
  process.exit(1);
}

await rm(output, { recursive: true, force: true });
await mkdir(output, { recursive: true });
for (const asset of ['index.html', 'styles.css', 'js']) {
  await cp(join(source, asset), join(output, asset), { recursive: true });
}
await writeFile(join(output, 'config.js'), `window.APP_CONFIG = ${JSON.stringify({ API_BASE_URL: apiBaseUrl })};\n`);
console.log('Built frontend/dist with public API configuration.');
