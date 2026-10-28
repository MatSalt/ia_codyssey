import {test, expect} from '@playwright/test';

const html='<img src=x onerror="window.injected=true">';
const record={id:'2026-10-25',date:'2026-10-25',value:10,memo:html};
const summary={period:{start:'2026-10-24',end:'2026-10-25'},count:1,calendar_days:2,filled_zero_days:1,metrics:{total:10,daily_average:5,max:{value:10,dates:['2026-10-25']},min:{value:0,dates:['2026-10-24']}},comparison:{status:'zero_baseline',window_days:1,previous:{start:'2026-10-24',end:'2026-10-24',average:0},recent:{start:'2026-10-25',end:'2026-10-25',average:10},change_percent:null,trend:'increase',message:'기준값이 0이므로 변화율은 계산하지 않습니다.'},notable_memos:Array.from({length:120},()=>({...record}))};
const conversation={id:'saved-conversation',title:html,created_at:'2026-10-25T01:00:00Z',updated_at:'2026-10-25T01:00:00Z',messages:[{role:'user',content:'이전 질문',created_at:'2026-10-25T01:00:00Z'},{role:'assistant',content:html,created_at:'2026-10-25T01:00:00Z'}]};

test.beforeEach(async ({page})=>{
  page.on('pageerror',error=>{throw error;});
});

async function fixture(page,{records=[record],conversations=[conversation],chat}={}){
  const calls=[];
  await page.route('**/api/**',async route=>{
    const req=route.request(), path=new URL(req.url()).pathname, method=req.method();
    const body=req.postDataJSON(); calls.push({path,method,body});
    const json=(value,status=200)=>route.fulfill({status,json:value});
    if(path==='/api/data/summary'&&method==='GET')return json(records.length?summary:{...summary,count:0,period:null,calendar_days:0,filled_zero_days:0,metrics:{total:0,daily_average:null,max:null,min:null},comparison:{...summary.comparison,status:'insufficient_data',window_days:0,previous:null,recent:null,trend:'insufficient_data'},notable_memos:[]});
    if(path==='/api/data'&&method==='GET')return json({items:records});
    if(path==='/api/data'&&method==='POST'){records.push({id:body.date,...body});return json(records.at(-1),201);}
    if(path.startsWith('/api/data/')&&method==='PUT'){Object.assign(records.find(x=>x.id===path.split('/').at(-1)),body);return json(records[0]);}
    if(path.startsWith('/api/data/')&&method==='DELETE'){records=[];return route.fulfill({status:204});}
    if(path==='/api/conversations'&&method==='GET')return json({items:conversations.map(({messages,...item})=>item)});
    if(path===`/api/conversations/${conversation.id}`&&method==='GET')return json(conversation);
    if(path===`/api/conversations/${conversation.id}`&&method==='DELETE'){conversations=[];return route.fulfill({status:204});}
    if(path==='/api/chat'&&method==='POST')return chat?chat(route,body):json({conversation_id:conversation.id,answer:html});
    throw new Error(`Unexpected HTTP request: ${method} ${path}`);
  });
  await page.goto('/');
  await expect(page.locator('#data-status')).not.toContainText('불러오는 중');
  return calls;
}

test('null change rate remains unavailable and HTML stays inert across all rendered surfaces',async({page})=>{
  await fixture(page);
  await expect(page.locator('.comparison')).toContainText('변화율: 계산 불가');
  await expect(page.locator('.comparison')).not.toContainText('0.00%');
  await expect(page.locator('.comparison')).toContainText('직전 1일 2026-10-24');
  await expect(page.locator('.comparison')).toContainText('최근 1일 2026-10-25');
  await expect(page.locator('#data-list')).toContainText(html);
  await expect(page.locator('.memo-list')).toContainText(html);
  await expect(page.locator('.memo-list li')).toHaveCount(120);
  expect(await page.locator('.memo-list').evaluate(el=>el.getBoundingClientRect().height)).toBeLessThanOrEqual(220);
  await expect(page.locator('.memo-list')).toHaveAttribute('tabindex','0');
  await page.locator('.memo-list').focus();
  await page.keyboard.press('ArrowDown');
  await expect.poll(()=>page.locator('.memo-list').evaluate(el=>el.scrollTop)).toBeGreaterThan(0);
  await page.locator('.history-open').click();
  await expect(page.locator('#chat-messages')).toContainText(html);
  await page.getByLabel('데이터에 질문하기').fill(html);
  await page.locator('#chat-send').click();
  await expect(page.locator('#chat-status')).toContainText('저장되었습니다');
  await expect(page.locator('#chat-messages img, #data-list img, #history-list img, #summary-content img')).toHaveCount(0);
  expect(await page.evaluate(()=>window.injected)).toBeUndefined();
});

for(const code of [422,503])test(`${code} clears pending chat controls and permits retry`,async({page})=>{
  let release, attempts=0; const pending=new Promise(resolve=>{release=resolve;});
  await fixture(page,{chat:async route=>{if(++attempts>1)return route.fulfill({json:{conversation_id:conversation.id,answer:'재시도 응답'}});await pending;return route.fulfill({status:code,json:{detail:'처리 실패'}});}});
  await page.getByLabel('데이터에 질문하기').fill('최근 추세');
  await page.locator('#chat-send').click();
  await expect(page.locator('#chat-send')).toBeDisabled();
  await expect(page.locator('#chat-question')).toBeDisabled();
  await expect(page.locator('#chat-status')).toContainText('준비하고');
  release();
  await expect(page.locator('#chat-status')).toContainText(`${code} · 처리 실패`);
  await expect(page.locator('#chat-send')).toBeEnabled();
  await expect(page.locator('#chat-question')).toBeEnabled();
  await expect(page.locator('#chat-question')).toHaveValue('최근 추세');
  await expect(page.locator('#chat-messages .message')).toHaveCount(0);
  await page.locator('#chat-send').click();
  await expect(page.locator('#chat-messages')).toContainText('재시도 응답');
  await expect(page.locator('#chat-status')).toContainText('저장되었습니다');
});

test('204 deletion refreshes records and summary and clears restored conversation',async({page})=>{
  const calls=await fixture(page);page.on('dialog',dialog=>dialog.accept());
  await page.getByRole('button',{name:'2026-10-25 기록 삭제',exact:true}).click();
  await expect(page.locator('#data-list tr')).toHaveCount(0);
  await expect(page.locator('#summary-content')).toContainText('아직 분석할 데이터가 없습니다');
  expect(calls.filter(x=>x.path==='/api/data'&&x.method==='GET')).toHaveLength(2);
  expect(calls.filter(x=>x.path==='/api/data/summary')).toHaveLength(2);
  await page.locator('.history-open').click();
  await page.locator('#history-list .danger').click();
  await expect(page.locator('#history-list li')).toHaveCount(0);
  await expect(page.locator('#chat-title-current')).toHaveText('새 대화');
  await expect(page.locator('#history-status')).toContainText('저장된 대화가 없습니다');
});

test('restoring history sends the next question with the same conversation ID',async({page})=>{
  let calls=await fixture(page);
  await page.reload();
  await page.locator('.history-open').click();
  await expect(page.locator('#chat-messages')).toContainText('이전 질문');
  await page.getByLabel('데이터에 질문하기').fill('이어서 알려줘');
  await page.locator('#chat-send').click();
  await expect(page.locator('#chat-status')).toContainText('저장되었습니다');
  expect(calls.find(x=>x.path==='/api/chat').body).toEqual({message:'이어서 알려줘',conversation_id:'saved-conversation'});
  expect(calls.some(x=>x.path==='/api/conversations'&&x.method==='POST')).toBe(false);
});

test('empty screen has accessible keyboard input and no page overflow',async({page})=>{
  await fixture(page,{records:[],conversations:[]});
  await expect(page.locator('#data-status')).toContainText('아직 저장된 기록이 없습니다');
  await expect(page.locator('#summary-content')).toContainText('아직 분석할 데이터가 없습니다');
  await expect(page.locator('#history-status')).toContainText('저장된 대화가 없습니다');
  await page.keyboard.press('Tab');
  await expect(page.getByRole('link',{name:'본문으로 이동'})).toBeFocused();
  await page.locator('#chat-new').focus();
  await page.keyboard.press('Enter');
  await expect(page.getByLabel('데이터에 질문하기')).toBeFocused();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
});
