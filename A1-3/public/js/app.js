'use strict';

const form = document.querySelector('#coach-form');
const source = document.querySelector('#source-text');
const submitButton = document.querySelector('#submit-button');
const sampleButton = document.querySelector('#sample-button');
const inputError = document.querySelector('#input-error');
const count = document.querySelector('#char-count');
const tabs = [...document.querySelectorAll('[role="tab"]')];
const levels = ['A1', 'A2', 'B1', 'B2'];
const names = { A1: '첫걸음', A2: '기초', B1: '중급', B2: '중상급' };
const states = {
  empty: document.querySelector('#empty-state'),
  loading: document.querySelector('#loading-state'),
  error: document.querySelector('#request-error'),
  result: document.querySelector('#result'),
};
let selectedLevel = 'A1';
let results = null;
let resultSource = '';
let busy = false;
const SAMPLE = 'Last Saturday, Mina visited a small library near her home. Although she usually reads on her phone, she decided to borrow a printed book. The librarian recommended a story about a young traveller. Mina enjoyed the first chapter so much that she stayed until the library closed.';

function updateCount() {
  const length = Array.from(source.value.trim()).length;
  count.textContent = `${length.toLocaleString('en-US')} / 1,500`;
  count.classList.toggle('over-limit', length > 1500);
  source.removeAttribute('aria-invalid');
  inputError.hidden = true;
}

function showState(state) {
  for (const [name, element] of Object.entries(states)) element.hidden = name !== state;
}

function selectLevel(level, focus = false) {
  selectedLevel = level;
  for (const tab of tabs) {
    const selected = tab.dataset.level === level;
    tab.setAttribute('aria-selected', String(selected));
    tab.tabIndex = selected ? 0 : -1;
    if (selected && focus) tab.focus();
  }
  document.querySelector('#result-content').setAttribute('aria-labelledby', `tab-${level}`);
  if (results && !busy) renderResult();
}

function renderResult() {
  const item = results.find(result => result.level === selectedLevel);
  document.querySelector('#result-level').textContent = `${selectedLevel} · ${names[selectedLevel]}`;
  document.querySelector('#rewritten-text').textContent = item.rewritten_text;
  document.querySelector('#coach-note').textContent = item.note_ko;
  document.querySelector('#result-source').textContent = resultSource;
  const list = document.querySelector('#changes-list');
  list.replaceChildren();
  for (const change of item.changes) {
    const li = document.createElement('li');
    const pair = document.createElement('p');
    pair.className = 'expression-pair';
    for (const [className, value] of [['before', change.original], ['arrow', '→'], ['after', change.rewritten]]) {
      const span = document.createElement('span');
      span.className = className;
      span.textContent = value;
      if (className !== 'arrow') span.lang = 'en';
      pair.append(span);
    }
    const reason = document.createElement('p');
    reason.className = 'change-reason';
    reason.textContent = change.reason_ko;
    li.append(pair, reason);
    list.append(li);
  }
  document.querySelector('#no-changes').hidden = item.changes.length !== 0;
  showState('result');
}

function validResults(data) {
  if (!Array.isArray(data?.results) || data.results.length !== 4) return false;
  return levels.every(level => data.results.filter(item => item?.level === level).length === 1)
    && data.results.every(item => typeof item.rewritten_text === 'string' && item.rewritten_text.trim()
      && typeof item.note_ko === 'string' && item.note_ko.trim()
      && Array.isArray(item.changes) && item.changes.length <= 2
      && item.changes.every(change => ['original', 'rewritten', 'reason_ko']
        .every(key => typeof change?.[key] === 'string' && change[key].trim())));
}

form.addEventListener('submit', async event => {
  event.preventDefault();
  if (busy) return;
  const text = source.value.trim();
  if (!text || Array.from(text).length > 1500) {
    inputError.textContent = !text ? '변환할 영어 글을 입력해 주세요.' : '영어 글을 1,500자 이내로 줄여 주세요.';
    inputError.hidden = false;
    source.setAttribute('aria-invalid', 'true');
    source.focus();
    return;
  }
  busy = true;
  results = null;
  submitButton.disabled = true;
  sampleButton.disabled = true;
  inputError.hidden = true;
  source.removeAttribute('aria-invalid');
  document.querySelector('#submit-label').textContent = '네 레벨을 만들고 있어요';
  document.querySelector('#output-panel').setAttribute('aria-busy', 'true');
  const status = document.querySelector('#request-status');
  status.textContent = 'A1부터 B2까지 변환 중입니다.';
  showState('loading');
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 30000);
  try {
    const response = await fetch('/api/rewrite', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }), signal: controller.signal,
    });
    let data;
    try { data = await response.json(); }
    catch (error) {
      if (error.name === 'AbortError') throw error;
      throw new Error('서버 응답을 읽지 못했어요. 잠시 후 다시 시도해 주세요.');
    }
    if (!response.ok) throw new Error(typeof data?.error?.message === 'string'
      ? data.error.message : 'AI 요청을 처리하지 못했어요. 잠시 후 다시 시도해 주세요.');
    if (!validResults(data)) throw new Error('네 레벨의 결과를 완성하지 못했어요. 다시 시도해 주세요.');
    results = data.results;
    resultSource = text;
    busy = false;
    selectLevel('A1');
    status.textContent = '네 레벨의 변환이 완료되었습니다. A1 결과가 표시됩니다.';
  } catch (error) {
    const message = error.name === 'AbortError'
      ? '응답이 늦어지고 있어요. 글을 조금 줄이거나 잠시 후 다시 시도해 주세요.'
      : error instanceof TypeError ? '인터넷 연결을 확인하고 다시 시도해 주세요.' : error.message;
    document.querySelector('#request-error-message').textContent = message;
    showState('error');
    status.textContent = '변환하지 못했습니다. 안내 메시지를 확인해 주세요.';
  } finally {
    clearTimeout(timeout);
    busy = false;
    submitButton.disabled = false;
    sampleButton.disabled = false;
    document.querySelector('#submit-label').textContent = '네 레벨로 바꾸기';
    document.querySelector('#output-panel').setAttribute('aria-busy', 'false');
  }
});

source.addEventListener('input', updateCount);
sampleButton.addEventListener('click', () => {
  source.value = SAMPLE;
  updateCount();
  source.focus();
});
for (const tab of tabs) {
  tab.addEventListener('click', () => selectLevel(tab.dataset.level));
  tab.addEventListener('keydown', event => {
    let index = levels.indexOf(selectedLevel);
    if (event.key === 'ArrowRight') index = (index + 1) % 4;
    else if (event.key === 'ArrowLeft') index = (index + 3) % 4;
    else if (event.key === 'Home') index = 0;
    else if (event.key === 'End') index = 3;
    else return;
    event.preventDefault();
    selectLevel(levels[index], true);
  });
}
updateCount();
