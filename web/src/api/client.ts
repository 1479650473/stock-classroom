// HTTP client for the stock-classroom Web API.
// - Dev: same-origin '/api' (vite proxy -> 127.0.0.1:5000)
// - Prod (Tauri webview): absolute http://127.0.0.1:5000

const BASE: string =
  (import.meta.env.VITE_API_BASE as string) ||
  (import.meta.env.DEV ? '' : 'http://127.0.0.1:5000')

export class ApiError extends Error {
  code: string
  http: number
  retriable: boolean
  constructor(http: number, code: string, message: string, retriable = false) {
    super(message)
    this.http = http
    this.code = code
    this.retriable = retriable
  }
}

interface Envelope<T> {
  code: number
  data: T
  message?: string
  error?: { code: string; message: string; retriable?: boolean }
}

interface RequestOptions {
  signal?: AbortSignal
  /** GET 结果缓存毫秒数：TTL 内直接返回缓存（不产生网络请求）。0/未设 = 不缓存 */
  ttl?: number
  /** true = 忽略缓存强制刷新（页面的「刷新」按钮用） */
  fresh?: boolean
}

async function request<T>(method: string, path: string, body?: unknown, params?: Record<string, unknown>, opts?: RequestOptions): Promise<T> {
  let url = BASE + path
  if (params) {
    const qs = new URLSearchParams()
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null && v !== '') qs.set(k, String(v))
    }
    const s = qs.toString()
    if (s) url += (url.includes('?') ? '&' : '?') + s
  }
  let resp: Response
  try {
    resp = await fetch(url, {
      method,
      headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: opts?.signal,
    })
  } catch (e) {
    if ((e as Error).name === 'AbortError') throw e
    throw new ApiError(0, 'network', '无法连接后端服务(请确认 run_web.py 已启动)', true)
  }
  let payload: Envelope<T>
  try {
    payload = (await resp.json()) as Envelope<T>
  } catch {
    throw new ApiError(resp.status, 'bad_response', `服务返回异常 (${resp.status})`)
  }
  if (!resp.ok || payload.code !== 0) {
    const e = payload.error
    throw new ApiError(resp.status || payload.code, e?.code || 'error', e?.message || payload.message || '请求失败', e?.retriable)
  }
  return payload.data
}

// ───────────────────────── GET 缓存（TTL + 并发去重） ─────────────────────────
// 目的：切页面回来不再重新拉一遍（数据在 TTL 内直接命中），
// 同时把并发请求合并（多组件同时 mount 时只发一次）。
interface CacheEntry {
  at: number
  data: unknown
}
const GET_CACHE = new Map<string, CacheEntry>()
const INFLIGHT = new Map<string, Promise<unknown>>()

function cacheKey(path: string, params?: Record<string, unknown>): string {
  if (!params) return path
  const entries = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== null && v !== '')
    .sort(([a], [b]) => a.localeCompare(b))
  return path + '?' + entries.map(([k, v]) => `${k}=${String(v)}`).join('&')
}

export function clearApiCache(prefix?: string) {
  if (!prefix) {
    GET_CACHE.clear()
    return
  }
  for (const k of [...GET_CACHE.keys()]) if (k.startsWith(prefix)) GET_CACHE.delete(k)
}

export const api = {
  get: async <T>(path: string, params?: Record<string, unknown>, opts?: RequestOptions): Promise<T> => {
    const ttl = opts?.ttl ?? 0
    if (ttl <= 0 && !opts?.fresh) {
      return request<T>('GET', path, undefined, params, opts)
    }
    const key = cacheKey(path, params)
    if (!opts?.fresh) {
      const hit = GET_CACHE.get(key)
      if (hit && Date.now() - hit.at < ttl) return hit.data as T
      const running = INFLIGHT.get(key)
      if (running) return running as Promise<T>
    }
    const p = request<T>('GET', path, undefined, params, opts)
      .then((data) => {
        GET_CACHE.set(key, { at: Date.now(), data })
        return data
      })
      .finally(() => {
        INFLIGHT.delete(key)
      })
    INFLIGHT.set(key, p)
    return p
  },
  post: <T>(path: string, body?: unknown, params?: Record<string, unknown>, opts?: RequestOptions) => request<T>('POST', path, body, params, opts),
  del: <T>(path: string, opts?: RequestOptions) => request<T>('DELETE', path, undefined, undefined, opts),
  base: BASE,
}

export interface JobHandle {
  job_id: string
  status: string
  kind: string
}

// SSE stream for a job; returns a close() function.
export function streamJob(
  jobId: string,
  handlers: {
    onProgress?: (frame: Record<string, unknown>) => void
    onResult?: (result: unknown) => void
    onError?: (message: string) => void
  },
): () => void {
  const url = `${BASE}/api/jobs/${jobId}/stream`
  const es = new EventSource(url)
  let settled = false
  es.onmessage = (ev) => {
    let frame: Record<string, unknown>
    try {
      frame = JSON.parse(ev.data)
    } catch {
      return
    }
    const type = frame.type as string
    if (type === 'progress') handlers.onProgress?.(frame)
    else if (type === 'result' || type === 'done') {
      if (settled) return
      settled = true
      if (frame.status === 'failed' || frame.type === 'error') {
        handlers.onError?.((frame.error as string) || (frame.message as string) || '任务失败')
      } else {
        handlers.onResult?.(frame.result)
      }
      es.close()
    } else if (type === 'error') {
      if (settled) return
      settled = true
      handlers.onError?.((frame.message as string) || '任务失败')
      es.close()
    }
  }
  es.onerror = () => {
    if (settled) return
    settled = true
    handlers.onError?.('连接中断')
    es.close()
  }
  return () => es.close()
}
