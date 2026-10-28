export async function request(path, options = {}) {
  const base = globalThis.window?.APP_CONFIG?.API_BASE_URL;
  if (typeof base !== 'string' || !base.trim()) throw new Error('API_BASE_URL 설정이 없습니다. config.js를 생성한 뒤 다시 열어주세요.');
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 60000);
  const external = options.signal;
  const abort = () => controller.abort();
  if (external?.aborted) abort();
  external?.addEventListener('abort', abort, { once: true });
  try {
    const headers = new Headers(options.headers);
    let body = options.body;
    if (body !== undefined && typeof body !== 'string') { body = JSON.stringify(body); headers.set('Content-Type', 'application/json'); }
    const response = await fetch(`${base.trim().replace(/\/+$/, '')}/${path.replace(/^\/+/, '')}`, { ...options, body, headers, signal: controller.signal });
    if (response.status === 204) return null;
    const raw = await response.text();
    let data;
    try { data = raw ? JSON.parse(raw) : null; } catch { data = null; }
    if (!response.ok) {
      const detail = data?.detail;
      const description = Array.isArray(detail) ? detail.map(item => `${(item.loc || []).join('.')}: ${item.msg || '입력 오류'}`).join('; ') : typeof detail === 'string' ? detail : '요청을 처리하지 못했습니다.';
      const error = new Error(`${response.status} · ${description}`);
      error.status = response.status; error.detail = detail; throw error;
    }
    if (raw && data === null) throw new Error('서버 응답을 읽을 수 없습니다. 다시 시도해주세요.');
    return data;
  } catch (error) {
    if (controller.signal.aborted) throw new Error(external?.aborted ? '요청을 취소했습니다.' : '응답이 60초를 초과했습니다. 잠시 후 다시 시도해주세요.');
    if (error instanceof TypeError) throw new Error('서버에 연결할 수 없습니다. 연결과 API 주소를 확인해주세요.');
    throw error;
  } finally { clearTimeout(timeout); external?.removeEventListener('abort', abort); }
}
