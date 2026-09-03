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

export const api = {
  get: <T>(path: string, params?: Record<string, unknown>, opts?: RequestOptions) => request<T>('GET', path, undefined, params, opts),
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
      if (frame.status === 'failed' || frame.type === 'error') {
        handlers.onError?.((frame.error as string) || (frame.message as string) || '任务失败')
      } else {
        handlers.onResult?.(frame.result)
      }
      es.close()
    } else if (type === 'error') {
      handlers.onError?.((frame.message as string) || '任务失败')
      es.close()
    }
  }
  es.onerror = () => {
    handlers.onError?.('连接中断')
    es.close()
  }
  return () => es.close()
}
