import {defineConfig} from '@playwright/test';
import base from './playwright.config.js';
export default defineConfig({...base,testMatch:'integration.spec.js',fullyParallel:false,workers:1,
  use:{...base.use,baseURL:'http://127.0.0.1:4174'},
  webServer:{...base.webServer,command:'node tests/serve-integration.mjs',url:'http://127.0.0.1:4174/docs'}
});
