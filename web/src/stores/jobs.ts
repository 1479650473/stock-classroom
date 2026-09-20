// 全局任务中心：统一管理后端 job 生命周期，页面切换/组件卸载不中断。
//
// 后端 backend/api/jobman.py 的 job 记录保留 6 小时，SSE 支持 `since` 重放，
// 因此：① SSE 连接由本 store 持有，切页面不会断；② 刷新页面后 restore() 可恢复。
import { defineStore } from 'pinia'
import { api, streamJob } from '@/api/client'
import { useToastStore } from './toast'
import { getDesktopPrefs, systemNotify } from '@/lib/tauri'

export type JobStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'

export interface JobRecord {
  id: string
  kind: string
  title: string
  status: JobStatus
  pct: number
  msg: string
  result?: unknown
  error?: string
  /** 关联页面路由，任务卡片可一键跳转 */
  route?: string
  startedAt: number
  finishedAt?: number
  /** 完成后自增，页面可 watch 它触发结果刷新 */
  doneTick?: number
}

/** SSE 连接句柄不放进 Pinia state，避免响应式代理包裹 EventSource 回调 */
const STREAMS = new Map<string, () => void>()

/** kind → 中文标题（刷新恢复时后端只回 kind） */
export const KIND_LABEL: Record<string, string> = {
  pipeline: '数据更新',
  optimize: '策略进化',
  backtest: '策略回测',
  research: '因子研究',
  picks: '选股评分',
  flow: '全流程',
  agent: 'AI 任务',
  deep: '个股深挖',
  news: '事件驱动',
  guard: '持仓守护',
  trader: 'AI 操盘手决策',
  trader_all: '全体交易员决策',
  trader_replay: '交易员回放',
}

let _notifyOn = true
void (async () => {
  const p = await getDesktopPrefs()
  if (p) _notifyOn = p.system_notify
})()

/** 系统通知（Windows 通知中心）；最小化到托盘时也能看到结果 */
async function notifyDesktop(title: string, body: string) {
  if (!_notifyOn) return
  await systemNotify(title, body)
}

export const useJobsStore = defineStore('jobs', {
  state: () => ({
    map: {} as Record<string, JobRecord>,
    order: [] as string[], // 创建时间倒序
    drawerOpen: false,
  }),

  getters: {
    list(state): JobRecord[] {
      return state.order.map((id) => state.map[id]).filter(Boolean) as JobRecord[]
    },
    running(): JobRecord[] {
      return this.list.filter((j) => j.status === 'queued' || j.status === 'running')
    },
    activeCount(): number {
      return this.running.length
    },
    finished(): JobRecord[] {
      return this.list.filter((j) => j.status !== 'queued' && j.status !== 'running').slice(0, 12)
    },
  },

  actions: {
    byKind(kind: string): JobRecord[] {
      return this.list.filter((j) => j.kind === kind)
    },
    /** 该类型当前正在跑的任务（同类型同时只应有一个） */
    activeByKind(kind: string): JobRecord | null {
      return this.running.find((j) => j.kind === kind) || null
    },

    upsert(rec: JobRecord) {
      if (!this.map[rec.id]) this.order.unshift(rec.id)
      this.map[rec.id] = { ...this.map[rec.id], ...rec }
      if (this.order.length > 60) {
        const drop = this.order.splice(60)
        for (const id of drop) delete this.map[id]
      }
    },

    /**
     * 提交后端 job 并订阅进度。返回 job_id；提交失败返回 null。
     * submit 由调用方提供（各业务接口不同），store 只负责生命周期。
     */
    async run(opts: {
      kind: string
      title: string
      submit: () => Promise<{ job_id: string }>
      route?: string
      silent?: boolean
    }): Promise<string | null> {
      const toast = useToastStore()
      try {
        const job = await opts.submit()
        this.upsert({
          id: job.job_id,
          kind: opts.kind,
          title: opts.title,
          status: 'queued',
          pct: 0,
          msg: '已提交，等待执行…',
          route: opts.route,
          startedAt: Date.now(),
        })
        this.attach(job.job_id, opts.silent)
        return job.job_id
      } catch (e) {
        const m = e instanceof Error ? e.message : String(e)
        toast.error(`${opts.title}提交失败：${m}`)
        return null
      }
    },

    /** 订阅（或重连）某个 job 的 SSE 流；重复调用安全 */
    attach(jobId: string, silent = false) {
      if (STREAMS.has(jobId)) return
      const toast = useToastStore()
      const close = streamJob(jobId, {
        onProgress: (frame) => {
          const rec = this.map[jobId]
          if (!rec) return
          if (rec.status === 'queued') rec.status = 'running'
          if (typeof frame.pct === 'number') rec.pct = Math.max(0, Math.min(100, frame.pct))
          const msg = frame.msg ?? frame.message ?? frame.phase
          if (msg) rec.msg = String(msg)
        },
        onResult: (result) => {
          STREAMS.delete(jobId)
          const rec = this.map[jobId]
          if (rec) {
            rec.status = 'succeeded'
            rec.pct = 100
            rec.msg = '已完成'
            rec.result = result
            rec.finishedAt = Date.now()
            rec.doneTick = (rec.doneTick || 0) + 1
          }
          if (!silent) toast.success(`${rec?.title || '任务'}已完成`)
          void notifyDesktop(`${rec?.title || '任务'}已完成`, '点击托盘图标回到工作台')
        },
        onError: (message) => {
          STREAMS.delete(jobId)
          const rec = this.map[jobId]
          if (rec) {
            rec.status = 'failed'
            rec.error = message
            rec.msg = message
            rec.finishedAt = Date.now()
            rec.doneTick = (rec.doneTick || 0) + 1
          }
          toast.error(`${rec?.title || '任务'}失败：${message}`)
          void notifyDesktop(`${rec?.title || '任务'}失败`, String(message).slice(0, 120))
        },
      })
      STREAMS.set(jobId, close)
    },

    /** 应用启动时从后端恢复任务（刷新页面后进度不丢） */
    async restore() {
      try {
        const rows = await api.get<Array<Record<string, unknown>>>('/api/jobs', { limit: 50 })
        for (const row of rows) {
          const id = String(row.job_id || '')
          if (!id || this.map[id]) continue
          const status = String(row.status || '') as JobStatus
          const finishedAt = row.finished_at ? Number(row.finished_at) * 1000 : undefined
          // 跳过超过 6h 的旧记录，避免任务中心堆历史
          if (finishedAt && Date.now() - finishedAt > 6 * 3600 * 1000) continue
          const kind = String(row.kind || 'task')
          const live = status === 'queued' || status === 'running'
          this.upsert({
            id,
            kind,
            title: KIND_LABEL[kind] || kind,
            status,
            pct: status === 'succeeded' ? 100 : 0,
            msg:
              status === 'succeeded'
                ? '已完成'
                : status === 'failed'
                  ? String(row.error || '失败')
                  : '执行中…',
            error: row.error ? String(row.error) : undefined,
            result: row.result ?? undefined,
            startedAt: row.created_at ? Number(row.created_at) * 1000 : Date.now(),
            finishedAt,
          })
          if (live) this.attach(id, true)
        }
      } catch {
        /* 后端未启动时静默，不影响前端启动 */
      }
    },

    /**
     * 等待 job 结束并返回结果。不依赖调用方组件生命周期，
     * 因此页面切换/卸载也不会让等待挂起（切回来仍能拿到结果）。
     */
    waitDone(
      jobId: string,
      timeoutMs = 30 * 60 * 1000,
    ): Promise<{ ok: boolean; result?: unknown; error?: string; status: JobStatus }> {
      const snapshot = (rec: JobRecord) => ({
        ok: rec.status === 'succeeded',
        result: rec.result,
        error: rec.error,
        status: rec.status,
      })
      const isDone = (rec?: JobRecord) =>
        !!rec && (rec.status === 'succeeded' || rec.status === 'failed' || rec.status === 'cancelled')

      return new Promise((resolve) => {
        const cur = this.map[jobId]
        if (isDone(cur)) {
          resolve(snapshot(cur as JobRecord))
          return
        }
        this.attach(jobId)
        const timer = window.setInterval(() => {
          const rec = this.map[jobId]
          if (isDone(rec)) {
            window.clearInterval(timer)
            window.clearTimeout(guard)
            resolve(snapshot(rec as JobRecord))
          }
        }, 150)
        const guard = window.setTimeout(() => {
          window.clearInterval(timer)
          const rec = this.map[jobId]
          resolve(rec ? snapshot(rec) : { ok: false, error: '等待超时', status: 'failed' })
        }, timeoutMs)
      })
    },

    async cancel(jobId: string) {
      const toast = useToastStore()
      try {
        await api.post(`/api/jobs/${jobId}/cancel`)
        const rec = this.map[jobId]
        if (rec) {
          rec.status = 'cancelled'
          rec.msg = '已取消'
          rec.finishedAt = Date.now()
        }
        STREAMS.get(jobId)?.()
        STREAMS.delete(jobId)
      } catch (e) {
        toast.error('取消失败：' + (e instanceof Error ? e.message : String(e)))
      }
    },

    dismiss(jobId: string) {
      STREAMS.get(jobId)?.()
      STREAMS.delete(jobId)
      delete this.map[jobId]
      this.order = this.order.filter((id) => id !== jobId)
    },

    clearFinished() {
      for (const rec of [...this.finished]) this.dismiss(rec.id)
    },
  },
})
