import {test,expect} from '@playwright/test';

test('real local API persists a conversation and refreshes answer context after editing',async({page,request})=>{
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  // The dedicated fake server is memory-only. Isolate the viewport runs.
  for(const path of ['/api/data','/api/conversations']){
    const response=await request.get(path);expect(response.ok()).toBe(true);
    for(const item of (await response.json()).items)expect((await request.delete(`${path}/${item.id}`)).status()).toBe(204);
  }
  await page.goto('/');
  await expect(page.locator('#summary-content')).toContainText('아직 분석할 데이터가 없습니다');
  await page.getByLabel('날짜',{exact:true}).fill('2026-01-01');
  await page.getByLabel('열람 횟수',{exact:true}).fill('4');
  await page.locator('#data-save').click();
  await expect(page.locator('#data-list tr')).toHaveCount(1);
  await expect(page.locator('.stat').filter({hasText:'총 열람'}).locator('.stat-value')).toHaveText('4회');
  await page.getByLabel('데이터에 질문하기').fill('총 열람 횟수는?');
  const firstResponse=page.waitForResponse(r=>r.url().endsWith('/api/chat')&&r.request().method()==='POST');
  await page.locator('#chat-send').click();
  const first=await firstResponse;expect(first.status()).toBe(200);const id=(await first.json()).conversation_id;
  expect(first.request().postDataJSON()).toEqual({message:'총 열람 횟수는?'});
  await expect(page.locator('#chat-messages')).toContainText('총 4회');
  await page.reload();
  await page.locator('.history-open').click();
  await expect(page.locator('#chat-messages .message')).toHaveCount(2);
  await expect(page.locator('#chat-messages')).toContainText('총 4회');
  await page.getByRole('button',{name:'2026-01-01 기록 수정',exact:true}).click();
  await page.getByLabel('열람 횟수',{exact:true}).fill('9');
  await page.locator('#data-save').click();
  await expect(page.locator('#data-list')).toContainText('9회');
  await expect(page.locator('.stat').filter({hasText:'총 열람'}).locator('.stat-value')).toHaveText('9회');
  await page.getByLabel('데이터에 질문하기').fill('바뀐 합계는?');
  const nextResponse=page.waitForResponse(r=>r.url().endsWith('/api/chat')&&r.request().method()==='POST');
  await page.locator('#chat-send').click();
  const next=await nextResponse;expect(next.status()).toBe(200);
  expect(next.request().postDataJSON()).toEqual({message:'바뀐 합계는?',conversation_id:id});
  expect((await next.json()).conversation_id).toBe(id);
  await expect(page.locator('#chat-messages .message')).toHaveCount(4);
  await expect(page.locator('#chat-messages')).toContainText('총 9회');
  expect(errors).toEqual([]);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});
