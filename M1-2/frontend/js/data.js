export function initData(root, api) {
  const form = root.querySelector('#data-form'), list = root.querySelector('#data-list'), status = root.querySelector('#data-status');
  const date = form.elements.date, value = form.elements.value, memo = form.elements.memo;
  const save = root.querySelector('#data-save'), cancel = root.querySelector('#data-cancel');
  let editing = null, busy = false, revision = 0;
  function reset() { editing = null; form.reset(); date.disabled = false; save.textContent = '기록 추가'; cancel.hidden = true; }
  cancel.addEventListener('click', reset);
  function tell(message, error = false) { status.textContent = message; status.classList.toggle('error', error); }
  async function refresh() {
    const ticket = ++revision; tell('기록을 불러오는 중입니다.');
    try {
      const { items } = await api('/api/data'); if (ticket !== revision) return;
      list.replaceChildren();
      for (const record of items) {
        const row = document.createElement('tr');
        for (const text of [record.date, `${record.value.toLocaleString('ko-KR')}회`, record.memo || '—']) { const cell = document.createElement('td'); cell.textContent = text; row.append(cell); }
        const actions = document.createElement('td');
        const edit = document.createElement('button'); edit.type = 'button'; edit.className = 'secondary'; edit.textContent = '수정'; edit.setAttribute('aria-label', `${record.date} 기록 수정`);
        edit.addEventListener('click', () => { if (busy) return; editing = record.id; date.value = record.date; date.disabled = true; value.value = record.value; memo.value = record.memo; save.textContent = '수정 저장'; cancel.hidden = false; value.focus(); });
        const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'danger'; remove.textContent = '삭제'; remove.setAttribute('aria-label', `${record.date} 기록 삭제`);
        remove.addEventListener('click', async () => {
          if (busy || !window.confirm(`${record.date} 기록을 삭제할까요? 기간 내 누락 날짜는 요약에서 0회로 계산됩니다.`)) return;
          busy = true; remove.disabled = true;
          try { await api(`/api/data/${encodeURIComponent(record.id)}`, { method: 'DELETE' }); if (editing === record.id) reset(); root.dispatchEvent(new CustomEvent('data-changed')); }
          catch (error) { tell(error.message, true); } finally { busy = false; remove.disabled = false; }
        });
        actions.append(edit, remove); row.append(actions); list.append(row);
      }
      tell(items.length ? `${items.length}개의 기록 · 날짜 오름차순` : '아직 저장된 기록이 없습니다. 첫 일별 기록을 추가해주세요.');
    } catch (error) { if (ticket === revision) tell(error.message, true); }
  }
  form.addEventListener('submit', async event => {
    event.preventDefault(); if (busy || !form.reportValidity()) return;
    const amount = Number(value.value); if (!Number.isSafeInteger(amount) || amount < 0) { tell('열람 횟수는 0 이상의 정수로 입력해주세요.', true); return; }
    busy = true; save.disabled = true; cancel.disabled = true; tell('저장 중입니다.');
    const payload = { value: amount, memo: memo.value };
    if (!editing) payload.date = date.value;
    try { await api(editing ? `/api/data/${encodeURIComponent(editing)}` : '/api/data', { method: editing ? 'PUT' : 'POST', body: payload }); reset(); root.dispatchEvent(new CustomEvent('data-changed')); }
    catch (error) { tell(error.message, true); } finally { busy = false; save.disabled = false; cancel.disabled = false; }
  });
  root.querySelector('#data-refresh').addEventListener('click', refresh);
  root.addEventListener('data-changed', refresh);
  refresh();
}
