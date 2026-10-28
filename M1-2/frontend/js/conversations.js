export function initConversations(root, api) {
  const list = root.querySelector('#history-list'), status = root.querySelector('#history-status'); let revision = 0, selection = 0;
  const deleting = new Set(), deleted = new Set();
  function tell(text, error = false) { status.textContent = text; status.classList.toggle('error', error); }
  root.addEventListener('conversation-changed', event => { if (event.detail?.action === 'new') selection++; refresh(); });
  async function refresh() {
    const ticket = ++revision; tell('대화 목록을 불러오는 중입니다.');
    try {
      const {items} = await api('/api/conversations'); if (ticket !== revision) return;
      list.replaceChildren(); tell(items.length ? `${items.length}개의 대화 · 최근 수정순` : '저장된 대화가 없습니다. AI 비서에게 첫 질문을 보내보세요.');
      for (const item of items) {
        if (deleted.has(item.id)) continue;
        const row = document.createElement('li'), open = document.createElement('button'), remove = document.createElement('button'); open.type = remove.type = 'button'; open.className = 'history-open'; open.textContent = item.title; open.disabled = deleting.has(item.id);
        const time = document.createElement('small'); const parsed = new Date(item.updated_at); time.textContent = Number.isNaN(parsed.getTime()) ? item.updated_at : parsed.toLocaleString('ko-KR'); open.append(time);
        open.addEventListener('click', async () => {
          if (deleting.has(item.id) || deleted.has(item.id)) return;
          const ticket = ++selection; open.disabled = true; tell('대화를 불러오는 중입니다.');
          try { const conversation = await api(`/api/conversations/${encodeURIComponent(item.id)}`); if (ticket !== selection || deleting.has(item.id) || deleted.has(item.id)) return; root.dispatchEvent(new CustomEvent('conversation-selected', {detail:conversation})); tell('대화를 불러왔습니다. AI 비서에서 질문을 이어갈 수 있습니다.'); root.querySelector('#chat').scrollIntoView({behavior:'smooth'}); }
          catch(error) { if (ticket === selection) tell(error.message, true); } finally {open.disabled = deleting.has(item.id) || deleted.has(item.id);}
        });
        remove.disabled = deleting.has(item.id); remove.className = 'danger'; remove.textContent = '삭제'; remove.setAttribute('aria-label', `${item.title} 대화 삭제`);
        remove.addEventListener('click', async () => {
          if (deleting.has(item.id) || deleted.has(item.id) || !window.confirm('이 대화를 삭제할까요? 삭제한 대화는 복구할 수 없습니다.')) return;
          ++selection; deleting.add(item.id); remove.disabled = true; open.disabled = true;
          try { await api(`/api/conversations/${encodeURIComponent(item.id)}`, {method:'DELETE'}); deleted.add(item.id); ++selection; root.dispatchEvent(new CustomEvent('conversation-deleted', {detail:item.id})); await refresh(); }
          catch(error) {deleting.delete(item.id); await refresh(); tell(error.message, true);} finally {deleting.delete(item.id); remove.disabled = deleted.has(item.id); open.disabled = deleted.has(item.id);}
        });
        row.append(open, remove); list.append(row);
      }
    } catch(error) {if (ticket === revision) tell(error.message, true);}
  }
  root.querySelector('#history-refresh').addEventListener('click', refresh); refresh();
}
