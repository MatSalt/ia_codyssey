const number = value => value == null ? '계산 불가' : Number(value).toLocaleString('ko-KR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
export function initSummary(root, api) {
  const status = root.querySelector('#summary-status'), content = root.querySelector('#summary-content'); let revision = 0;
  const node = (tag, text, cls) => { const el = document.createElement(tag); el.textContent = text; if (cls) el.className = cls; return el; };
  async function refresh() {
    const ticket = ++revision; status.textContent = '요약을 불러오는 중입니다.'; status.classList.remove('error');
    try {
      const s = await api('/api/data/summary'); if (ticket !== revision) return;
      content.replaceChildren(); status.textContent = '';
      if (!s.count) { content.append(node('p', '아직 분석할 데이터가 없습니다. 일별 기록을 추가해주세요.', 'empty')); return; }
      content.append(node('p', `${s.period.start} — ${s.period.end} · 저장 ${s.count}건 / 달력 ${s.calendar_days}일 · 누락 ${s.filled_zero_days}일 보완`, 'period'));
      const stats = node('div', '', 'stats');
      for (const [label, value, note] of [
        ['총 열람', `${s.metrics.total.toLocaleString('ko-KR')}회`, '분석 기간 전체'],
        ['일평균 열람', `${number(s.metrics.daily_average)}회`, `${s.calendar_days}일 기준`],
        ['최대 열람', s.metrics.max ? `${s.metrics.max.value.toLocaleString('ko-KR')}회` : '계산 불가', s.metrics.max?.dates.join(', ') || ''],
        ['최소 열람', s.metrics.min ? `${s.metrics.min.value.toLocaleString('ko-KR')}회` : '계산 불가', s.metrics.min?.dates.join(', ') || '']
      ]) { const card = node('div', '', 'stat'); card.append(node('p', label, 'stat-label'), node('p', value, 'stat-value'), node('p', note, 'stat-note')); stats.append(card); }
      content.append(stats);
      const c = s.comparison, comparison = node('div', '', 'comparison'); comparison.append(node('h3', '최근 열람 추세'));
      if (c.previous && c.recent) { comparison.append(node('p', `직전 ${c.window_days}일 ${c.previous.start} ~ ${c.previous.end} · 일평균 ${number(c.previous.average)}회`), node('p', `최근 ${c.window_days}일 ${c.recent.start} ~ ${c.recent.end} · 일평균 ${number(c.recent.average)}회`)); }
      const trend = {increase:'증가',decrease:'감소',unchanged:'유지',insufficient_data:'비교 기간 부족'}[c.trend] || '';
      comparison.append(node('p', `변화율: ${c.change_percent == null ? '계산 불가' : `${number(c.change_percent)}%`} · ${trend}`), node('p', c.message)); content.append(comparison);
      if (s.notable_memos.length) { content.append(node('h3', '기록에 남긴 메모')); const memos = node('ul', '', 'memo-list'); memos.tabIndex = 0; memos.setAttribute('aria-label', '기록에 남긴 메모'); for (const item of s.notable_memos) memos.append(node('li', `${item.date} · ${item.value}회 · ${item.memo}`)); content.append(memos); }
    } catch (error) { if (ticket === revision) { status.textContent = error.message; status.classList.add('error'); content.replaceChildren(); } }
  }
  root.querySelector('#summary-refresh').addEventListener('click', refresh); root.addEventListener('data-changed', refresh); refresh();
}
