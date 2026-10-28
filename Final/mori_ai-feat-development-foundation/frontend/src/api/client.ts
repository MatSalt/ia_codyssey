let csrf: string | undefined;
export function setCsrf(value?: string) { csrf = value; }
export function uploadHeaders(url: string, required: Record<string, string>, origin = window.location.origin): Record<string, string> {
  const target = new URL(url, origin);
  const headers = {...required};
  if (target.origin === origin && target.pathname.startsWith('/api/') && csrf) {
    headers['X-CSRF-Token'] = csrf;
  }
  return headers;
}
export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public details: Record<string,unknown> = {}, public retryable = false, public requestId?: string) { super(message); }
}
const messages: Record<number,string> = {401:'로그인이 만료되었습니다. 다시 로그인해 주세요.',403:'동의 또는 접근 권한을 확인해 주세요.',404:'사진첩이나 사진을 찾을 수 없습니다.',409:'다른 변경이 있습니다. 최신 내용을 확인한 뒤 다시 시도해 주세요.',413:'파일 용량이 너무 큽니다.',422:'파일 형식이나 입력값을 확인해 주세요.'};
export function errorText(error: unknown) { if(error instanceof DOMException && ['TimeoutError','AbortError'].includes(error.name))return '응답을 기다리는 시간이 지났습니다. 같은 요청으로 다시 시도해 주세요.'; if(error instanceof TypeError)return '서버에 연결하지 못했습니다. 연결을 확인하고 다시 시도해 주세요.'; return error instanceof Error ? error.message : '요청을 처리하지 못했습니다.'; }
export async function api<T>(path: string, options: {method?: string; body?: unknown; key?: string; signal?: AbortSignal} = {}): Promise<T> {
  const method = options.method ?? 'GET';
  const headers: Record<string,string> = {};
  if (options.body !== undefined) headers['Content-Type'] = 'application/json';
  if (method !== 'GET' && csrf) headers['X-CSRF-Token'] = csrf;
  if (options.key) headers['Idempotency-Key'] = options.key;
  const url = path.startsWith('/api/') ? path : `/api/v1${path}`;
  // Completion verifies the immutable remote bytes before acknowledging acceptance.
  const timeoutMs = method === 'POST' && /^\/api\/v1\/albums\/[^/]+\/uploads\/[^/]+\/complete$/.test(url) ? 180000 : 30000;
  const response = await fetch(url, {method, headers, body: options.body === undefined ? undefined : JSON.stringify(options.body), credentials:'same-origin', cache:'no-store', signal:options.signal ? AbortSignal.any([options.signal, AbortSignal.timeout(timeoutMs)]) : AbortSignal.timeout(timeoutMs)});
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    const code = payload.error?.code ?? 'HTTP_ERROR';
    if (response.status === 401) window.dispatchEvent(new Event('mori:unauthorized'));
    throw new ApiError(response.status, code, messages[response.status] ?? '연결에 문제가 있습니다. 잠시 후 다시 시도해 주세요.', payload.error?.details ?? {}, payload.error?.retryable ?? false, payload.request_id);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()).data as T;
}
