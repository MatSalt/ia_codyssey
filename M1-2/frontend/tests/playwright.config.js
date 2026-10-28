import { defineConfig } from '@playwright/test';
import {existsSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
const systemChrome=process.platform==='darwin' && existsSync('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome');
export default defineConfig({
  testDir: '.', testMatch: 'e2e.spec.js', fullyParallel: true,
  use: { baseURL: 'http://127.0.0.1:4173', channel: process.env.PLAYWRIGHT_CHANNEL || (systemChrome?'chrome':undefined) },
  projects: [ { name: 'desktop', use: { viewport: {width:1280,height:900} } }, {name:'mobile', use:{viewport:{width:360,height:800}}} ],
  webServer: {cwd:fileURLToPath(new URL('..',import.meta.url)), command:'node tests/serve.mjs', url:'http://127.0.0.1:4173', reuseExistingServer:false},
});
