// Browser integration checks use mocked HTTP responses, never paid AI calls.
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const fixture = {results:['A1','A2','B1','B2'].map(level=>({level,rewritten_text:`${level}: The event will happen later.`,changes:[{original:'postponed',rewritten:'happen later',reason_ko:'쉬운 표현입니다.'}],note_ko:'문장을 비교해 보세요.'}))};
(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.CHROME_PATH?{executablePath:process.env.CHROME_PATH}:{})});
 const page=await browser.newPage();
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 let calls=0;let responder=route=>route.fulfill({json:fixture});
 await page.route('**/api/rewrite',async route=>{calls++;await responder(route)});
 await page.goto(process.env.TEST_URL||'http://127.0.0.1:4173');
 for(const width of [390,768,1440]){
  await page.setViewportSize({width,height:1000});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,`overflow at ${width}`);
 }
 await page.locator('#submit-button').click();
 assert.equal(await page.locator('#input-error').isVisible(),true);assert.equal(calls,0);
 await page.locator('#source-text').fill('a'.repeat(1501));await page.locator('#submit-button').click();assert.equal(calls,0);
 await page.locator('#sample-button').click();assert.ok((await page.locator('#source-text').inputValue()).length>200);
 await page.locator('#submit-button').click();await page.locator('#result').waitFor();
 assert.equal(calls,1);assert.match(await page.locator('#rewritten-text').innerText(),/^A1:/);
 for(const level of ['A2','B1','B2']) {await page.locator(`#tab-${level}`).click();assert.match(await page.locator('#rewritten-text').innerText(),new RegExp(`^${level}:`));}
 assert.equal(calls,1,'tabs must not generate again');
 await page.locator('#tab-B2').press('ArrowRight');assert.equal(await page.locator('#tab-A1').getAttribute('aria-selected'),'true');
 // Keep the result attached to the submitted source even if the user types meanwhile.
 let release;responder=async route=>{await new Promise(resolve=>release=resolve);await route.fulfill({json:fixture})};
 await page.locator('#source-text').fill('Original request text.');await page.locator('#submit-button').click();
 await page.waitForFunction(()=>document.querySelector('#submit-button').disabled);
 await page.locator('#source-text').fill('Edited during request.');await page.locator('#tab-B1').click();
 while(!release) await new Promise(resolve=>setTimeout(resolve,5));release();await page.locator('#result').waitFor();
 assert.equal(await page.locator('#result-source').textContent(),'Original request text.');
 for(const status of [429,502,504]){
  responder=route=>route.fulfill({status,json:{error:{message:`오류 ${status}`}}});
  await page.locator('#submit-button').click();await page.locator('#request-error').waitFor();
  assert.match(await page.locator('#request-error-message').innerText(),new RegExp(String(status)));
  assert.equal(await page.locator('#source-text').inputValue(),'Edited during request.');
  assert.equal(await page.locator('#submit-button').isEnabled(),true);
 }
 responder=route=>route.fulfill({body:'<html>Bad gateway</html>',contentType:'text/html'});
 await page.locator('#submit-button').click();await page.locator('#request-error').waitFor();assert.match(await page.locator('#request-error-message').innerText(),/읽지/);
 responder=route=>route.fulfill({json:{results:fixture.results.slice(0,3)}});
 await page.locator('#submit-button').click();await page.locator('#request-error').waitFor();assert.match(await page.locator('#request-error-message').innerText(),/완성/);
 const unsafe=JSON.parse(JSON.stringify(fixture));unsafe.results[0].rewritten_text='<img src=x onerror="window.injected=true">';
 responder=route=>route.fulfill({json:unsafe});await page.locator('#submit-button').click();await page.locator('#result').waitFor();
 assert.equal(await page.locator('#rewritten-text img').count(),0);assert.equal(await page.evaluate(()=>window.injected),undefined);
 // Exercise the actual 30s timeout using the browser clock, not a real wait.
 await page.clock.install();responder=()=>new Promise(()=>{});
 await page.locator('#submit-button').click();await page.locator('#loading-state').waitFor();await page.clock.fastForward(31000);
 await page.locator('#request-error').waitFor();assert.match(await page.locator('#request-error-message').innerText(),/늦어/);
 assert.equal(await page.locator('#submit-button').isEnabled(),true);
 assert.deepEqual(errors,[]);console.log('PASS: responsive 390/768/1440, input boundaries, sample, four tabs, keyboard, source snapshot, 429/502/504, malformed JSON, partial output, XSS, timeout, retry controls.');
 await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
