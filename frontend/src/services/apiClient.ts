/**
 * Secure API client for the ResearchFlow backend (`/api/v1`).
 * Uses the HttpOnly session cookie and attaches the in-memory CSRF token on state-changing requests.
 * Nothing secret is stored in localStorage or exposed through VITE_* variables.
 */
export const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL || '/api/v1';

let inMemoryCsrfToken: string | null = null;
const unauthorizedListeners = new Set<() => void>();

export function setCsrfToken(token: string | null): void {
  inMemoryCsrfToken = token;
}

export function onUnauthorized(fn: () => void): () => void {
  unauthorizedListeners.add(fn);
  return () => unauthorizedListeners.delete(fn);
}

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, message: string, detail: unknown) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

function messageFrom(detail: unknown, status: number): string {
  if (typeof detail === 'string') return detail;
  if (detail && typeof detail === 'object' && 'message' in detail) return String((detail as { message: unknown }).message);
  if (Array.isArray(detail) && detail.length && typeof detail[0] === 'object' && detail[0] && 'msg' in detail[0]) {
    return String((detail[0] as { msg: unknown }).msg);
  }
  return status === 0 ? 'Network unavailable. Check your connection.' : `Request failed (${status}).`;
}

interface RequestOptions {
  method?: string;
  json?: unknown;
  body?: BodyInit;
  headers?: Record<string, string>;
  signal?: AbortSignal;
}

async function send(path: string, opts: RequestOptions = {}): Promise<Response> {
  const method = (opts.method || 'GET').toUpperCase();
  const headers = new Headers(opts.headers || {});
  let body = opts.body;
  if (opts.json !== undefined) {
    headers.set('Content-Type', 'application/json');
    body = JSON.stringify(opts.json);
  }
  if (['POST', 'PATCH', 'PUT', 'DELETE'].includes(method) && inMemoryCsrfToken) {
    headers.set('X-CSRF-Token', inMemoryCsrfToken);
  }
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, { method, headers, body, credentials: 'include', signal: opts.signal });
  } catch (err) {
    if ((err as Error).name === 'AbortError') throw err;
    throw new ApiError(0, messageFrom(null, 0), null);
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    const detail = (payload as { detail?: unknown }).detail;
    if (response.status === 401) unauthorizedListeners.forEach((fn) => fn());
    throw new ApiError(response.status, messageFrom(detail, response.status), detail);
  }
  return response;
}

export async function apiRequest<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const res = await send(path, opts);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  get: <T>(path: string, signal?: AbortSignal) => apiRequest<T>(path, { signal }),
  post: <T>(path: string, json?: unknown) => apiRequest<T>(path, { method: 'POST', json: json ?? {} }),
  patch: <T>(path: string, json: unknown) => apiRequest<T>(path, { method: 'PATCH', json }),
  putJson: <T>(path: string, json: unknown) => apiRequest<T>(path, { method: 'PUT', json }),
  put: <T>(path: string, body: BodyInit) => apiRequest<T>(path, { method: 'PUT', body, headers: { 'Content-Type': 'application/octet-stream' } }),
  del: <T>(path: string) => apiRequest<T>(path, { method: 'DELETE' }),
  form: <T>(path: string, form: FormData) => apiRequest<T>(path, { method: 'POST', body: form }),
  text: async (path: string) => (await send(path)).text(),
  blob: async (path: string, method = 'GET') => {
    const res = await send(path, { method });
    return { blob: await res.blob(), headers: res.headers };
  },
};

/** Multipart upload with progress (fetch cannot report upload progress). Sends the CSRF token. */
export function uploadWithProgress<T>(path: string, form: FormData, method: 'POST' | 'PUT', onProgress: (fraction: number) => void): Promise<T> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open(method, `${API_BASE_URL}${path}`);
    xhr.withCredentials = true;
    if (inMemoryCsrfToken) xhr.setRequestHeader('X-CSRF-Token', inMemoryCsrfToken);
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    xhr.onload = () => {
      let payload: unknown = {};
      try { payload = JSON.parse(xhr.responseText || '{}'); } catch { /* non-JSON error page */ }
      if (xhr.status >= 200 && xhr.status < 300) return resolve(payload as T);
      if (xhr.status === 401) unauthorizedListeners.forEach((fn) => fn());
      const detail = (payload as { detail?: unknown }).detail;
      reject(new ApiError(xhr.status, messageFrom(detail, xhr.status), detail));
    };
    xhr.onerror = () => reject(new ApiError(0, messageFrom(null, 0), null));
    xhr.send(form);
  });
}

export function filenameFromDisposition(headers: Headers, fallback: string): string {
  const cd = headers.get('Content-Disposition') || '';
  const m = /filename="?([^";]+)"?/i.exec(cd);
  return m ? m[1] : fallback;
}

export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

/** Download an authenticated resource through fetch (keeps cookies + CSRF), then save it. */
export async function downloadFile(path: string, fallbackName: string, method = 'GET'): Promise<Headers> {
  const { blob, headers } = await api.blob(path, method);
  saveBlob(blob, filenameFromDisposition(headers, fallbackName));
  return headers;
}
