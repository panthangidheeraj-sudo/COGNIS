/**
 * Low-level transport for the live COGNIS backend.
 * Components never call fetch() directly — they use the typed api modules.
 */

export const API_MODE: 'mock' | 'live' = import.meta.env.VITE_API_MODE === 'live' ? 'live' : 'mock';
export const API_BASE_URL: string = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? '/api';

export type ApiErrorCode =
  | 'not_found'
  | 'ambiguous'
  | 'blocked'
  | 'rate_limited'
  | 'unavailable'
  | 'invalid'
  | 'network'
  | 'unknown';

/** Error shape surfaced to the UI. Never contains stack traces or secrets. */
export class ApiError extends Error {
  readonly code: ApiErrorCode;
  readonly status: number;
  /** Optional structured payload (e.g. ambiguous candidates). */
  readonly details?: unknown;
  constructor(code: ApiErrorCode, message: string, status = 0, details?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.status = status;
    this.details = details;
  }
}

function codeForStatus(status: number): ApiErrorCode {
  if (status === 404) return 'not_found';
  if (status === 409) return 'ambiguous';
  if (status === 403 || status === 451) return 'blocked';
  if (status === 429) return 'rate_limited';
  if (status === 400 || status === 422) return 'invalid';
  if (status >= 500) return 'unavailable';
  return 'unknown';
}

type Query = Record<string, string | number | boolean | undefined | null>;

function buildUrl(path: string, query?: Query): string {
  const base = API_BASE_URL.replace(/\/$/, '');
  const qs = query
    ? Object.entries(query)
        .filter(([, v]) => v !== undefined && v !== null && v !== '')
        .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
        .join('&')
    : '';
  return `${base}${path}${qs ? `?${qs}` : ''}`;
}

async function request<T>(method: string, path: string, opts: { query?: Query; body?: unknown; signal?: AbortSignal } = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(buildUrl(path, opts.query), {
      method,
      signal: opts.signal,
      headers: opts.body !== undefined ? { 'Content-Type': 'application/json', Accept: 'application/json' } : { Accept: 'application/json' },
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
      credentials: 'same-origin',
    });
  } catch (err) {
    if ((err as Error).name === 'AbortError') throw err;
    throw new ApiError('network', 'The COGNIS backend could not be reached.');
  }
  if (!res.ok) {
    let payload: { message?: string; code?: ApiErrorCode; details?: unknown } = {};
    try {
      payload = await res.json();
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(payload.code ?? codeForStatus(res.status), payload.message ?? `Request failed (${res.status}).`, res.status, payload.details);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const http = {
  get: <T>(path: string, query?: Query, signal?: AbortSignal) => request<T>('GET', path, { query, signal }),
  post: <T>(path: string, body?: unknown, signal?: AbortSignal) => request<T>('POST', path, { body: body ?? {}, signal }),
  patch: <T>(path: string, body: unknown) => request<T>('PATCH', path, { body }),
  put: <T>(path: string, body: unknown) => request<T>('PUT', path, { body }),
  del: <T>(path: string) => request<T>('DELETE', path),
};

/* -------------------------------------------------------------------------- */
/*  Server-sent events with reconnect + de-duplication                        */
/* -------------------------------------------------------------------------- */

export interface StreamHandlers<E> {
  onEvent: (event: E) => void;
  onOpen?: () => void;
  onReconnecting?: () => void;
  onError?: (error: ApiError) => void;
}

export type Unsubscribe = () => void;

/**
 * Opens an SSE stream. Events must be JSON with a numeric `seq`.
 * On disconnect it reconnects with `lastSeq` so the backend can replay;
 * duplicates are dropped client-side.
 */
export function openEventStream<E extends { seq: number; type: string }>(
  path: string,
  handlers: StreamHandlers<E>,
  opts: { lastSeq?: number; terminalTypes?: string[]; maxRetries?: number } = {},
): Unsubscribe {
  let lastSeq = opts.lastSeq ?? 0;
  let closed = false;
  let retries = 0;
  let source: EventSource | null = null;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const terminal = new Set(opts.terminalTypes ?? []);
  const maxRetries = opts.maxRetries ?? 6;

  const connect = () => {
    if (closed) return;
    source = new EventSource(buildUrl(path, { lastSeq }));
    source.onopen = () => {
      retries = 0;
      handlers.onOpen?.();
    };
    source.onmessage = (msg) => {
      let event: E;
      try {
        event = JSON.parse(msg.data) as E;
      } catch {
        return;
      }
      if (event.seq <= lastSeq) return; // de-duplicate replays
      lastSeq = event.seq;
      handlers.onEvent(event);
      if (terminal.has(event.type)) {
        closed = true;
        source?.close();
      }
    };
    source.onerror = () => {
      source?.close();
      if (closed) return;
      if (retries >= maxRetries) {
        handlers.onError?.(new ApiError('network', 'Lost connection to the research stream.'));
        return;
      }
      retries += 1;
      handlers.onReconnecting?.();
      timer = setTimeout(connect, Math.min(8000, 500 * 2 ** retries));
    };
  };
  connect();
  return () => {
    closed = true;
    if (timer) clearTimeout(timer);
    source?.close();
  };
}
