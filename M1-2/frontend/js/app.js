import { request } from './api.js';
import { initData } from './data.js';
import { initSummary } from './summary.js';
import { initChat } from './chat.js';
import { initConversations } from './conversations.js';
const root = document.querySelector('main');
const base = window.APP_CONFIG?.API_BASE_URL;
if (typeof base !== 'string' || !base.trim()) {
  const error = document.querySelector('#config-error'); error.hidden = false;
  error.textContent = 'API_BASE_URL 설정이 없습니다. API 주소를 설정해 빌드하고 config.js가 로드되는지 확인해주세요.';
}
initData(root, request);
initSummary(root, request);
initChat(root, request);
initConversations(root, request);
