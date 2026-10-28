export function initChat(root, api) {
  const form = root.querySelector('#chat-form'), question = root.querySelector('#chat-question'), send = root.querySelector('#chat-send'), status = root.querySelector('#chat-status'), messages = root.querySelector('#chat-messages'), title = root.querySelector('#chat-title-current');
  let conversationId = null, generation = 0, pending = false;
  function render(items = []) {
    messages.replaceChildren();
    if (!items.length) { const empty = document.createElement('p'); empty.className = 'empty'; empty.textContent = '어떤 이야기가 궁금한가요? 예: 최근 열람 추세를 알려주세요.'; messages.append(empty); }
    for (const item of items) append(item.role, item.content);
  }
  function append(role, text) { const bubble = document.createElement('article'); bubble.className = `message ${role === 'user' ? 'user' : 'assistant'}`; const label = document.createElement('p'); label.className = 'message-label'; label.textContent = role === 'user' ? '나' : 'AI 비서'; const body = document.createElement('p'); body.className = 'message-content'; body.textContent = text; bubble.append(label, body); messages.append(bubble); messages.scrollTop = messages.scrollHeight; }
  function select(conversation) {
    generation++; conversationId = conversation?.id || null; title.textContent = conversation?.title || '새 대화'; render(conversation?.messages || []); status.textContent = pending ? '이전 질문을 처리 중입니다. 완료 후 새 질문을 보낼 수 있습니다.' : ''; status.classList.remove('error'); question.value = '';
  }
  root.addEventListener('conversation-selected', event => select(event.detail));
  root.addEventListener('conversation-deleted', event => { if (event.detail === conversationId) select(null); });
  root.querySelector('#chat-new').addEventListener('click', () => { select(null); root.dispatchEvent(new CustomEvent('conversation-changed', {detail:{action:'new'}})); question.focus(); });
  form.addEventListener('submit', async event => {
    event.preventDefault(); const text = question.value.trim(); if (pending || !text) { if (!text) { status.textContent = '질문을 입력해주세요.'; question.focus(); } return; }
    const ticket = generation, id = conversationId; pending = true; send.disabled = true; question.disabled = true; status.classList.remove('error'); status.textContent = '답변을 준비하고 있습니다…';
    const delay = setTimeout(() => { if (ticket === generation) status.textContent = '답변 생성에 시간이 걸리고 있습니다. 잠시만 기다려주세요. (최대 60초)'; }, 10000);
    try {
      const result = await api('/api/chat', {method:'POST', body:{message:text, ...(id ? {conversation_id:id} : {})}});
      if (ticket === generation) {
        if (!id) { messages.replaceChildren(); title.textContent = text.slice(0,40); }
        append('user', text); append('assistant', result.answer); conversationId = result.conversation_id; question.value = ''; status.textContent = '답변과 대화가 저장되었습니다.';
      }
      root.dispatchEvent(new CustomEvent('conversation-changed', {detail:{id:result.conversation_id, action:'saved'}}));
    } catch (error) { if (ticket === generation) { status.textContent = error.message; status.classList.add('error'); } }
    finally { clearTimeout(delay); pending = false; send.disabled = false; question.disabled = false; if (ticket !== generation) status.textContent = ''; }
  });
}
