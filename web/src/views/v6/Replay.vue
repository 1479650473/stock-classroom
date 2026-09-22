<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import SectionCard from '@/components/ui/SectionCard.vue'
import StatTile from '@/components/ui/StatTile.vue'
import EmptyGuide from '@/components/ui/EmptyGuide.vue'
import LoadingBlock from '@/components/ui/LoadingBlock.vue'
import Drawer from '@/components/ui/Drawer.vue'
import FormField from '@/components/ui/FormField.vue'
import Icon from '@/components/Icon.vue'
import KlineChart from '@/components/charts/KlineChart.vue'
import type { LwcBar, LwcMarker } from '@/components/charts/KlineChart.vue'
import { useEChart, cssVar } from '@/composables/useEChart'
import { tooltipStyle } from '@/lib/chartTheme'
import { streamJob } from '@/api/client'
import { useToastStore } from '@/stores/toast'
import { useJobsStore } from '@/stores/jobs'
import {
  getTraderReplays, getTraderProfiles, createTraderReplay, getTraderReplay,
  continueTraderReplay, distillTraderReplay, deleteTraderProfile, getKline,
} from '@/api'
import type { TraderProfile, TraderReplayDetail, TraderDecision } from '@/api'
import type { CandSnapshot } from '@/lib/cands'
import { candCount } from '@/lib/cands'
import CandDetail from '@/components/CandDetail.vue'

echarts.use([LineChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

const toast = useToastStore()
const jobs = useJobsStore()

const runs = ref<TraderProfile[]>([])
const liveTraders = ref<TraderProfile[]>([])
const current = ref<TraderReplayDetail | null>(null)
const currentId = ref<number | null>(null)
const loading = ref(true)
const detailLoading = ref(false)
const drawerOpen = ref(false)
const creating = ref(false)
const expanded = ref<Record<string, boolean>>({})

// ── 实时流 ──
interface StreamTool { name: string; args: Record<string, unknown>; result?: string; ok?: boolean }
interface StreamPos { code: string; name: string; qty: number; cost_price?: number; price?: number; float_pnl?: number; pnl_pct?: number | null }
interface StreamOrder { code: string; name?: string; side: string; qty: number; forced?: boolean; detail?: string; reason?: string; ok?: boolean; pnl_pct?: number }
interface StreamExec { ok?: boolean; detail?: string; price?: number; forced?: boolean }
interface StreamSettled {
  nav?: number; assets_before?: number; total_assets?: number; balance?: number
  positions?: number; positions_detail?: StreamPos[]
  plan: StreamOrder[]; executions: StreamExec[]; error?: string
}
interface StreamDay {
  date: string; index: number; total: number
  account?: { total_assets?: number; balance?: number }
  positions: number
  text: string
  tools: StreamTool[]
  decision?: { thinking: string; reflection: string; error?: string }
  settled?: StreamSettled
  warning?: string
  candidates?: CandSnapshot
  review?: { self_critique: string; lessons: string[]; style: string; rules?: string[]; trigger?: string }
  protection?: StreamOrder[]
  rejections?: { code?: string; side?: string; qty?: number; message?: string }[]
  expired?: { code?: string; name?: string; side?: string; qty?: number; days?: number; detail?: string }[]
  outlook?: { direction?: string; confidence?: number; reason?: string }
  outlook_score?: { actual?: string; actual_pct?: number; hit?: boolean }
  status: 'running' | 'settled'
}
const liveDays = ref<StreamDay[]>([])
const liveActive = ref(false)
const liveJobId = ref<string | null>(null)
const liveBox = ref<HTMLElement | null>(null)
let liveClose: (() => void) | null = null

// 树状折叠：月 → 日 → 内容；工具调用再单独折叠。默认只展开最近 3 天。
const treeOpen = ref<Record<string, boolean>>({})
function isOpen(key: string, def: boolean) { const v = treeOpen.value[key]; return v === undefined ? def : v }
function toggleNode(key: string, def: boolean) { treeOpen.value = { ...treeOpen.value, [key]: !isOpen(key, def) } }

const liveMonths = computed(() => {
  const map = new Map<string, StreamDay[]>()
  for (const d of liveDays.value) {
    const m = (d.date || '').slice(0, 7)
    if (!map.has(m)) map.set(m, [])
    map.get(m)!.push(d)
  }
  return [...map.entries()].map(([month, days]) => ({ month, days }))
})
const recentDates = computed(() => new Set(liveDays.value.slice(-3).map((d) => d.date)))
function dayOpen(d: StreamDay) { return recentDates.value.has(d.date) }
function monthOpen(m: { month: string; days: StreamDay[] }) { return m.days.some((d) => recentDates.value.has(d.date)) }
function expandAll() {
  const m: Record<string, boolean> = {}
  for (const d of liveDays.value) { m['m:' + d.date.slice(0, 7)] = true; m['d:' + d.date] = true; m['t:' + d.date] = true }
  treeOpen.value = m
}
function collapseAll() {
  const m: Record<string, boolean> = {}
  for (const d of liveDays.value) { m['m:' + d.date.slice(0, 7)] = false; m['d:' + d.date] = false; m['t:' + d.date] = false }
  treeOpen.value = m
}
function dayPnl(s?: StreamSettled): number | null {
  if (!s || s.assets_before == null || s.total_assets == null) return null
  return s.total_assets - s.assets_before
}
// 当日实际操作的股票集合（用于在候选池里标出模型选了哪些）
function pickedSet(orders?: { code?: string }[]): Set<string> {
  return new Set((orders || []).map((o) => String(o.code || '')).filter(Boolean))
}
function toggleCand(d: TraderDecision) { expanded.value['cd' + d.id] = !expanded.value['cd' + d.id] }
// 旧决策未记录候选池时返回空数组，不渲染空块
function candsOf(c?: unknown): CandSnapshot[] {
  const v = c as CandSnapshot | undefined
  return v && (v.picks || []).length ? [v] : []
}
function reviewFilled(r?: { self_critique?: string; lessons?: string[]; style?: string }) {
  return !!(r && (r.self_critique || (r.lessons || []).length || r.style))
}
const RULE_CN: Record<string, string> = {
  block_new_buy: '禁止开新仓', position_cap_pct: '单票仓位上限', stop_loss_pct: '止损线',
  max_new_positions_day: '单日新仓数上限', require_momentum_up: '买入需 20 日动量为正',
}
// 规则既可能是自省原文（对象），也可能是已经格式化过的短句（字符串）
function fmtRule(r: unknown): string {
  if (typeof r === 'string') return r
  const o = (r || {}) as { kind?: string; value?: number; regimes?: string[]; until?: string; reason?: string; text?: string }
  if (o.text) return o.text
  let txt = RULE_CN[o.kind || ''] || o.kind || ''
  if (o.value && o.kind !== 'require_momentum_up') txt += o.kind === 'max_new_positions_day' ? ` ${o.value} 个` : ` ${o.value}%`
  if (o.regimes?.length) txt += `（${o.regimes.join('/')}）`
  if (o.until) txt += ` · 至 ${o.until}`
  if (o.reason) txt += ` —— ${o.reason}`
  return txt
}
// 当前生效的纪律规则（自省结论 → 交易系统强制执行）
const ruleMemories = computed(() => {
  const out: { id: number; content: string }[] = []
  const seen = new Set<string>()
  for (const m of [...(current.value?.memory || [])].sort((a, b) => b.id - a.id)) {
    if (m.kind !== 'rule' || seen.has(m.code || '')) continue
    seen.add(m.code || '')
    try {
      out.push({ id: m.id, content: fmtRule(JSON.parse(m.content)) })
    } catch { out.push({ id: m.id, content: m.content }) }
  }
  return out
})
// 自我提升记录：优先展示教训/风格/市场观察，最新的在前
const ownMemories = computed(() => {
  const order: Record<string, number> = { lesson: 0, style: 1, market: 2, note: 3, thesis: 4, stage: 5 }
  return [...(current.value?.memory || [])]
    .filter((m) => m.kind !== 'rule')
    .sort((a, b) => (order[a.kind] ?? 9) - (order[b.kind] ?? 9) || b.id - a.id)
    .slice(0, 8)
})
function kindLabel(k: string) {
  return ({ lesson: '教训', style: '风格', market: '市场', note: '笔记', thesis: '持仓逻辑', stage: '阶段总结', rule: '纪律' } as Record<string, string>)[k] || k
}
const perfView = computed(() => {
  const t = current.value?.performance?.trading
  const n = current.value?.performance?.nav
  return {
    hasNav: !!n,
    cum: n?.cum_return_pct ?? null,
    dd: n?.max_drawdown_pct ?? null,
    dayWin: n?.day_win_rate_pct != null ? `${n.day_win_rate_pct}%` : '—',
    closed: t?.closed_count ?? 0,
    winRate: t?.closed_count ? `${t.win_rate_pct}%` : '—',
    pl: t?.profit_loss_ratio ?? '—',
    hold: t?.avg_hold_days != null ? `${t.avg_hold_days} 天` : '—',
    streak: t?.current_streak ? `${t.current_streak.type}${t.current_streak.count} 笔` : '—',
    streakUp: t?.current_streak?.type === '盈',
  }
})
function prettyArgs(t: StreamTool) {
  try { return JSON.stringify(t.args ?? {}, null, 2) } catch { return String(t.args) }
}

function curDay(): StreamDay | null {
  return liveDays.value.length ? liveDays.value[liveDays.value.length - 1] : null
}
function refreshLiveDetail() { loadDetail(true) }
function scrollLive() {
  const el = liveBox.value
  if (!el) return
  // 仅在接近底部时自动滚动，避免打断用户上翻
  if (el.scrollHeight - el.scrollTop - el.clientHeight < 160) {
    requestAnimationFrame(() => { el.scrollTop = el.scrollHeight })
  }
}

function startLive(jobId: string) {
  liveClose?.()
  liveActive.value = true
  liveJobId.value = jobId
  liveClose = streamJob(jobId, {
    onProgress: (frame) => {
      const ev = (frame as Record<string, unknown>).event as string | undefined
      if (!ev) return
      if (ev === 'day_start') {
        liveDays.value.push({
          date: String((frame as Record<string, unknown>).date || ''),
          index: Number((frame as Record<string, unknown>).index || 0),
          total: Number((frame as Record<string, unknown>).total || 0),
          account: (frame as Record<string, unknown>).account as StreamDay['account'],
          positions: (((frame as Record<string, unknown>).positions as unknown[]) || []).length,
          text: '', tools: [], status: 'running',
          candidates: (frame as Record<string, unknown>).candidates as CandSnapshot | undefined,
        })
      } else if (ev === 'review') {
        const d = curDay()
        if (d) {
          const f = frame as Record<string, unknown>
          d.review = {
            self_critique: String(f.self_critique || ''),
            lessons: (f.lessons as string[]) || [],
            style: String(f.style || ''),
            rules: (f.rules as string[]) || [],
            trigger: String(f.trigger || ''),
          }
        }
      } else if (ev === 'protection') {
        const d = curDay()
        if (d) d.protection = (frame as Record<string, unknown>).orders as StreamOrder[]
      } else if (ev === 'agent_text') {
        const d = curDay(); if (d) d.text += String((frame as Record<string, unknown>).delta || '')
      } else if (ev === 'tool_call') {
        const d = curDay()
        if (d) d.tools.push({ name: String((frame as Record<string, unknown>).name || ''),
                              args: ((frame as Record<string, unknown>).args as Record<string, unknown>) || {} })
      } else if (ev === 'tool_result') {
        const d = curDay()
        if (d) {
          const last = [...d.tools].reverse().find((t) => t.name === (frame as Record<string, unknown>).name && t.result === undefined)
          if (last) { last.ok = !!(frame as Record<string, unknown>).ok; last.result = String((frame as Record<string, unknown>).summary || '') }
        }
      } else if (ev === 'decision') {
        const d = curDay()
        if (d) d.decision = { thinking: String((frame as Record<string, unknown>).thinking || ''),
                              reflection: String((frame as Record<string, unknown>).reflection || ''),
                              error: String((frame as Record<string, unknown>).error || '') }
      } else if (ev === 'warning') {
        const d = curDay()
        if (d) d.warning = String((frame as Record<string, unknown>).message || '')
      } else if (ev === 'settled') {
        const d = curDay()
        if (d) {
          const f = frame as Record<string, unknown>
          d.settled = {
            nav: f.nav as number | undefined,
            assets_before: f.assets_before as number | undefined,
            total_assets: f.total_assets as number | undefined,
            balance: f.balance as number | undefined,
            positions: f.positions as number | undefined,
            positions_detail: (f.positions_detail as StreamPos[]) || [],
            plan: (f.plan as StreamOrder[]) || [],
            executions: (f.executions as StreamExec[]) || [],
            error: String(f.error || ''),
          }
          d.rejections = (f.rejections as StreamDay['rejections']) || []
          d.expired = (f.expired as StreamDay['expired']) || []
          d.status = 'settled'
        }
        refreshLiveDetail()
      } else if (ev === 'run_state') {
        const m = current.value?.profile.meta
        if (m) { m.cursor = String((frame as Record<string, unknown>).cursor || m.cursor); m.done_days = Number((frame as Record<string, unknown>).done_days || m.done_days) }
      }
      scrollLive()
    },
    onResult: () => { liveActive.value = false; liveClose = null; refreshLiveDetail(); loadRuns() },
    onError: () => { liveActive.value = false; liveClose = null },
  })
}

const draft = ref({ source_profile_id: 0, start_date: '2024-01-02', days: 30 })

const TOOL_LABEL: Record<string, string> = {
  get_account_summary: '查看账户', get_positions: '查看持仓', get_stock_price: '查价格',
  search_stock: '搜索股票', get_market_news: '读市场快讯', get_stock_news: '读个股新闻',
  get_regime: '看市场环境', get_candidates: '看候选股', preview_order: '预检委托',
  place_order: '下单', cancel_order: '撤单', remember: '记长期记忆', submit_decision: '提交决策',
}
function toolLabel(n: string) { return TOOL_LABEL[n] || n }
function toolArgs(t: { name: string; args: Record<string, unknown> }) {
  const a = t.args || {}
  if (t.name === 'place_order') return `${a.side === 'buy' ? '买' : '卖'} ${a.code} ${a.qty}`
  if (['get_stock_price', 'get_stock_news', 'search_stock'].includes(t.name) && a.code) return String(a.code)
  if (a.top || a.limit) return `top=${a.top || a.limit}`
  return ''
}

// K 线（按展开的交易日切片）
const klineBars = ref<Record<string, LwcBar[]>>({})
const klineLoading = ref<Record<string, boolean>>({})

const runningJob = computed(() => jobs.activeByKind('trader_replay'))
const isRunning = computed(() => !!runningJob.value)

async function loadRuns() {
  loading.value = true
  try {
    const [r, t] = await Promise.all([getTraderReplays(), getTraderProfiles()])
    runs.value = r.items || []
    liveTraders.value = t.items || []
    if (runs.value.length && !runs.value.some((x) => x.id === currentId.value)) {
      currentId.value = runs.value[0].id
    }
    if (!runs.value.length) currentId.value = null
  } catch (e) {
    toast.error('加载失败：' + (e instanceof Error ? e.message : String(e)))
  } finally {
    loading.value = false
  }
}

async function loadDetail(silent = false) {
  if (!currentId.value) { current.value = null; return }
  if (!silent) detailLoading.value = true
  try {
    current.value = await getTraderReplay(currentId.value, 120)
    if (!silent) klineBars.value = {}
  } catch (e) {
    if (!silent) toast.error('回放详情加载失败：' + (e instanceof Error ? e.message : String(e)))
  } finally {
    detailLoading.value = false
  }
}

onMounted(async () => {
  await loadRuns(); await loadDetail()
  // 刷新页面后，若还有回放任务在跑，重连实时流
  const running = jobs.byKind('trader_replay').find((j) => j.status === 'running' || j.status === 'queued')
  if (running) startLive(running.id)
})
watch(currentId, () => {
  // 切换回放时清空折叠状态：expanded 的键（hm:2024-02 / d<id>）会被不同回放共用，
  // 不清空就会出现「月份折叠后里面的日期永远不出现」的串档问题
  expanded.value = {}
  loadDetail()
})
watch(
  () => jobs.byKind('trader_replay').map((j) => `${j.id}:${j.doneTick || 0}:${j.status}`).join('|'),
  (v, o) => { if (v !== o) { loadRuns().then(() => loadDetail(true)) } },
)

function openCreate() {
  draft.value = {
    source_profile_id: liveTraders.value[0]?.id || 0,
    start_date: '2024-01-02', days: 30,
  }
  drawerOpen.value = true
}

async function create() {
  if (!draft.value.source_profile_id) { toast.error('请选择按哪个交易员回放'); return }
  creating.value = true
  try {
    const r = await createTraderReplay({
      source_profile_id: draft.value.source_profile_id,
      start_date: draft.value.start_date,
      days: Number(draft.value.days) || 30,
    })
    toast.success('回放已创建，正在逐日运行…')
    drawerOpen.value = false
    await loadRuns()
    currentId.value = r.profile.id
    liveDays.value = []
    treeOpen.value = {}
    jobs.attach(r.job.job_id)
    startLive(r.job.job_id)
  } catch (e) {
    toast.error('创建失败：' + (e instanceof Error ? e.message : String(e)))
  } finally {
    creating.value = false
  }
}

async function cont() {
  if (!currentId.value) return
  try {
    const r = await continueTraderReplay(currentId.value, 30)
    jobs.attach(r.job.job_id)
    liveDays.value = []
    treeOpen.value = {}
    startLive(r.job.job_id)
    toast.success('继续回放中…')
  } catch (e) {
    toast.error('续跑失败：' + (e instanceof Error ? e.message : String(e)))
  }
}

async function distill() {
  const run = current.value?.profile
  if (!run) return
  const src = (run.meta?.source_profile_id) || 0
  if (!src) { toast.error('找不到源交易员'); return }
  try {
    const r = await distillTraderReplay(run.id, src)
    toast.success(`已把 ${r.copied} 条回放经验写入「${r.target}」`)
  } catch (e) {
    toast.error('经验回流失败：' + (e instanceof Error ? e.message : String(e)))
  }
}

async function removeRun(p: TraderProfile) {
  if (!window.confirm(`删除回放「${p.name}」？其账户与全部逐日记录将一并删除。`)) return
  try {
    await deleteTraderProfile(p.id)
    toast.success('已删除')
    await loadRuns()
  } catch (e) {
    toast.error('删除失败：' + (e instanceof Error ? e.message : String(e)))
  }
}

// ── 展示辅助 ──
function fmtMoney(v?: number | null) {
  if (v == null) return '—'
  const abs = Math.abs(v)
  if (abs >= 1e8) return (v / 1e8).toFixed(2) + '亿'
  if (abs >= 1e4) return (v / 1e4).toFixed(2) + '万'
  return v.toLocaleString(undefined, { maximumFractionDigits: 2 })
}
function fmtPct(v?: number | null) {
  if (v == null) return '—'
  return (v >= 0 ? '+' : '') + v.toFixed(2) + '%'
}
function actionSummary(d: TraderDecision) {
  const n = d.plan?.length || 0
  if (!n) return '保持现状'
  return d.plan.map((o) => `${o.side === 'buy' ? '买' : '卖'} ${o.name || o.code} ${o.qty}`).join(' · ')
}
function dayNav(d: TraderDecision) { return d.nav_after }

// 月份头部日期范围提示（折叠时也能看出里面有哪些交易日）
function rangeHint(dates: string[]) {
  const s = dates.filter(Boolean).sort()
  if (!s.length) return ''
  return s.length > 1 ? `${s[0].slice(5)} ~ ${s[s.length - 1].slice(5)}` : s[0].slice(5)
}

// ── 逐日回放：月份 / 日期 树状折叠（默认展开最近 3 天）──
const histMonths = computed(() => {
  const map = new Map<string, TraderDecision[]>()
  for (const d of current.value?.decisions || []) {
    const m = (d.trade_date || '').slice(0, 7)
    if (!map.has(m)) map.set(m, [])
    map.get(m)!.push(d)
  }
  return [...map.entries()].map(([month, items]) => ({ month, items }))
})
const histRecent = computed(() => new Set((current.value?.decisions || []).slice(0, 3).map((d) => d.id)))
function histDayOpen(d: TraderDecision) {
  const v = expanded.value['d' + d.id]
  return v === undefined ? histRecent.value.has(d.id) : v
}
function toggleHistDay(d: TraderDecision) { expanded.value['d' + d.id] = !histDayOpen(d) }
function histMonthOpen(month: string) {
  const v = expanded.value['hm:' + month]
  if (v !== undefined) return v
  return (histMonths.value.find((m) => m.month === month)?.items || []).some((d) => histRecent.value.has(d.id))
}
function toggleHistMonth(month: string) { expanded.value['hm:' + month] = !histMonthOpen(month) }
function expandAllHist() {
  for (const d of current.value?.decisions || []) expanded.value['d' + d.id] = true
  for (const m of histMonths.value) expanded.value['hm:' + m.month] = true
}
function collapseAllHist() {
  for (const d of current.value?.decisions || []) expanded.value['d' + d.id] = false
  for (const m of histMonths.value) expanded.value['hm:' + m.month] = false
}

watch([current, expanded], () => {
  for (const d of current.value?.decisions || []) {
    if (histDayOpen(d)) {
      for (const c of dayCodes(d)) loadKline(c, d.trade_date)
    }
  }
}, { deep: true, immediate: true })

function dayCodes(d: TraderDecision): string[] {
  const codes = new Set<string>()
  for (const o of d.plan || []) codes.add(o.code)
  const pos = ((d.context as Record<string, unknown>)?.positions as { code: string }[]) || []
  for (const p of pos) codes.add(p.code)
  return [...codes].slice(0, 3)
}

async function loadKline(code: string, asOf: string) {
  const key = `${code}@${asOf}`
  if (klineBars.value[key] || klineLoading.value[key]) return
  klineLoading.value[key] = true
  try {
    const all = await getKline(code, 1600)
    const bars = (all as unknown as { date: string; open: number; high: number; low: number; close: number; volume: number }[])
      .map((b) => ({
        time: b.date.length === 8 ? `${b.date.slice(0, 4)}-${b.date.slice(4, 6)}-${b.date.slice(6, 8)}` : b.date,
        open: b.open, high: b.high, low: b.low, close: b.close, volume: b.volume,
      }))
      .filter((b) => b.time <= asOf)
    klineBars.value[key] = bars as LwcBar[]
  } catch {
    klineBars.value[key] = []
  } finally {
    klineLoading.value[key] = false
  }
}
/** 按代码推断涨跌停阈值（主板 10% / 创业科创 20% / 北交所 30%） */
function limitPctFor(code: string): number {
  const c = String(code || '')
  if (c.startsWith('30') || c.startsWith('68')) return 0.198
  if (/^(43|83|87|88|92)/.test(c)) return 0.298
  return 0.098
}

function markersFor(d: TraderDecision): LwcMarker[] {
  return (d.plan || []).map((o) => ({
    time: d.trade_date, position: o.side === 'buy' ? 'belowBar' : 'aboveBar',
    color: o.side === 'buy' ? cssVar('--up') : cssVar('--down'), shape: o.side === 'buy' ? 'arrowUp' : 'arrowDown',
    text: `${o.side === 'buy' ? '买' : '卖'}${o.qty}`,
  })) as LwcMarker[]
}

// ── 净值曲线（回放 vs 沪深300）──
const chartEl = ref<HTMLElement | null>(null)
const navSeries = computed(() => {
  const d = current.value
  if (!d) return [] as any[]
  return [{ name: '回放净值', type: 'line', showSymbol: false, smooth: true, lineStyle: { width: 2 },
            itemStyle: { color: cssVar('--accent', '#D4A574') },
            data: d.nav.map((p) => [p.date, p.nav]) }] as any[]
})
const chart = useEChart(chartEl, () => ({
  animation: false,
  grid: { left: 52, right: 16, top: 30, bottom: 36 },
  tooltip: { trigger: 'axis', ...tooltipStyle() },
  legend: { top: 2, textStyle: { color: cssVar('--text-sub', '#9AA4B2'), fontSize: 11 } },
  xAxis: { type: 'time', axisLabel: { color: cssVar('--text-faint', '#6B7280'), fontSize: 10, hideOverlap: true },
           axisLine: { lineStyle: { color: cssVar('--border', '#2A2E37') } } },
  yAxis: { type: 'value', scale: true,
           axisLabel: { color: cssVar('--text-faint', '#6B7280'), fontSize: 10, formatter: (v: number) => (v * 100).toFixed(0) + '%' },
           splitLine: { lineStyle: { color: cssVar('--border', '#2A2E37') } } },
  series: navSeries.value,
}))
watch([current, navSeries], async () => { await Promise.resolve(); chart.draw() })
</script>

<template>
  <div class="replay">
    <div class="bar">
      <div class="bar__left">
        <select v-model="currentId" class="ui-select">
          <option :value="null" disabled>选择回放</option>
          <option v-for="r in runs" :key="r.id" :value="r.id">
            {{ r.name }}（{{ r.meta?.done_days || 0 }}天）
          </option>
        </select>
        <span v-if="isRunning" class="running">回放中… {{ runningJob?.msg }}</span>
      </div>
      <button class="ui-btn ui-btn--primary" @click="openCreate"><Icon name="plus" :size="14" /><span>新建回放</span></button>
    </div>

    <LoadingBlock v-if="loading && !runs.length" :rows="4" />
    <EmptyGuide v-else-if="!runs.length" icon="backtest" title="还没有回放"
      desc="选一个交易员和一个历史起点，让它在过去的数据里逐日做模拟（无前视）。" >
      <template #action><button class="ui-btn ui-btn--primary" @click="openCreate">新建回放</button></template>
    </EmptyGuide>

    <template v-else-if="current">
      <!-- 头部 -->
      <div class="metrics">
        <StatTile label="回放天数" :value="current.profile.meta?.done_days || 0" unit="天" />
        <StatTile label="账户总资产" :value="fmtMoney(current.summary.total_assets)" icon="wallet" />
        <StatTile label="累计盈亏" :value="fmtMoney(current.summary.total_profit)"
          :trend="(current.summary.total_profit ?? 0) >= 0 ? 'up' : 'down'"
          :hint="fmtPct(current.summary.total_profit_pct)"
          :hint-trend="(current.summary.total_profit ?? 0) >= 0 ? 'up' : 'down'" />
        <StatTile label="持仓" :value="current.summary.positions ?? 0" unit="只" />
        <StatTile label="当前游标" :value="current.profile.meta?.cursor || '—'" />
      </div>

      <div class="actions">
        <span class="src">按「{{ current.profile.meta?.source_name }}」回放 · 起始 {{ current.profile.meta?.start_date }}</span>
        <button class="ui-btn" :disabled="isRunning" @click="cont"><Icon name="play" :size="13" /><span>继续 30 天</span></button>
        <button class="ui-btn" @click="distill"><Icon name="save" :size="13" /><span>经验回流到源交易员</span></button>
        <button class="ui-btn ui-btn--ghost" @click="removeRun(current.profile)"><Icon name="trash" :size="13" /><span>删除</span></button>
      </div>

      <SectionCard title="战绩与自我提升" desc="模型看到的真实成绩，以及它据此写下的教训">
        <div v-if="perfView.hasNav" class="perf">
          <div class="cell"><span class="cell__k">累计收益</span>
            <span class="cell__v" :class="(perfView.cum ?? 0) >= 0 ? 'up' : 'down'">
              {{ perfView.cum != null ? perfView.cum + '%' : '—' }}</span></div>
          <div class="cell"><span class="cell__k">最大回撤</span>
            <span class="cell__v down">{{ perfView.dd != null ? perfView.dd + '%' : '—' }}</span></div>
          <div class="cell"><span class="cell__k">已平仓</span>
            <span class="cell__v">{{ perfView.closed }} 笔</span></div>
          <div class="cell"><span class="cell__k">胜率</span>
            <span class="cell__v">{{ perfView.winRate }}</span></div>
          <div class="cell"><span class="cell__k">盈亏比</span>
            <span class="cell__v">{{ perfView.pl }}</span></div>
          <div class="cell"><span class="cell__k">平均持有</span>
            <span class="cell__v">{{ perfView.hold }}</span></div>
          <div class="cell"><span class="cell__k">当前连势</span>
            <span class="cell__v" :class="perfView.streakUp ? 'up' : 'down'">{{ perfView.streak }}</span></div>
          <div class="cell"><span class="cell__k">日胜率</span>
            <span class="cell__v">{{ perfView.dayWin }}</span></div>
        </div>
        <p v-else class="muted">暂无已平仓交易，积累几笔后这里会给出胜率与盈亏比。</p>

        <div class="memlist" style="margin-top:12px">
          <div class="block__title">自我提升记录（写入的长期记忆）</div>
          <div v-for="m in ownMemories" :key="m.id" class="memitem">
            <span class="mk">{{ kindLabel(m.kind) }}</span><span>{{ m.content }}</span>
          </div>
          <div v-if="!ownMemories.length" class="muted">还没有写入任何教训或风格，它在每次决策与每 3 日自省中会持续补充。</div>
        </div>

        <div class="memlist" style="margin-top:12px">
          <div class="block__title">生效中的纪律规则（自省结论 → 交易系统强制执行）</div>
          <div v-for="r in ruleMemories" :key="r.id" class="memitem memitem--rule">
            <span class="mk mk--rule">纪律</span><span>{{ r.content }}</span>
          </div>
          <div v-if="!ruleMemories.length" class="muted">
            暂无。模型在自省时会按战绩定下可执行的约束（如「减速期禁新仓」「止损收缩到 6%」），
            到期自动失效；系统每天收盘还会做兜底止损（默认 8%）。
          </div>
        </div>
      </SectionCard>

      <SectionCard v-if="liveActive || liveDays.length" title="实时回放"
        :desc="liveActive ? '模型正在逐日决策…' : '本次回放过程 · 按月份 / 日期折叠'">
        <template #actions>
          <span class="live-dot" :class="{ 'is-on': liveActive }" />
          <span class="live-state">{{ liveActive ? '进行中' : '已结束' }}</span>
          <button class="mini-btn" @click="expandAll">展开全部</button>
          <button class="mini-btn" @click="collapseAll">折叠全部</button>
        </template>
        <div ref="liveBox" class="live">
          <div v-for="m in liveMonths" :key="m.month" class="tnode">
            <div class="thead thead--m" @click="toggleNode('m:' + m.month, monthOpen(m))">
              <Icon :name="isOpen('m:' + m.month, monthOpen(m)) ? 'chevron-down' : 'chevron-right'" :size="15" class="chev" />
              <span class="tlabel tlabel--m">{{ m.month }}</span>
              <span class="tmeta">{{ m.days.length }} 个交易日</span>
              <span v-if="!isOpen('m:' + m.month, monthOpen(m))" class="tmeta tmeta--dim">
                {{ rangeHint(m.days.map((d) => d.date)) }}
              </span>
            </div>
            <div v-show="isOpen('m:' + m.month, monthOpen(m))" class="tbody">
              <div v-for="day in m.days" :key="day.date" class="tnode">
                <div class="thead thead--d" @click="toggleNode('d:' + day.date, dayOpen(day))">
                  <Icon :name="isOpen('d:' + day.date, dayOpen(day)) ? 'chevron-down' : 'chevron-right'" :size="14" class="chev" />
                  <span class="tlabel">{{ day.date }}</span>
                  <span class="tmeta">第 {{ day.index }}/{{ day.total }} 天</span>
                  <span v-if="day.settled" class="tchip" :class="(day.settled.nav ?? 1) >= 1 ? 'up' : 'down'">
                    净值 {{ Number(day.settled.nav ?? 1).toFixed(4) }}
                  </span>
                  <span v-if="day.account" class="tmeta tmeta--r">
                    开始前 {{ fmtMoney(day.account.total_assets) }} · 持仓 {{ day.positions }} 只
                  </span>
                  <span class="tstate" :class="day.status">{{ day.status === 'running' ? '进行中' : '已结算' }}</span>
                </div>

                <div v-show="isOpen('d:' + day.date, dayOpen(day))" class="tbody tbody--d">
                  <!-- 思考过程 -->
                  <div class="sec">
                    <div class="sec__label">思考过程</div>
                    <p class="sec__text">{{ day.text || (day.status === 'running' ? '正在思考…' : '（本次无旁白）') }}</p>
                  </div>

                  <!-- 最终决策 -->
                  <div v-if="day.decision" class="dec">
                    <div class="dec__head"><Icon name="sparkles" :size="13" /><span>最终决策</span></div>
                    <p class="dec__text">{{ day.decision.thinking || '（本轮未给出决策文本）' }}</p>
                    <p v-if="day.decision.reflection" class="dec__sub">复盘：{{ day.decision.reflection }}</p>
                  </div>

                  <div v-if="day.warning || day.decision?.error || day.settled?.error" class="warn">
                    <Icon name="alert" :size="12" />
                    <span>{{ day.warning || day.decision?.error || day.settled?.error }}</span>
                  </div>

                  <!-- 当日结算卡片 -->
                  <div v-if="day.settled" class="settle">
                    <div class="settle__top">
                      <span class="settle__tag"><Icon name="check" :size="12" />当日结算</span>
                      <span v-if="dayPnl(day.settled) != null" class="settle__pnl"
                        :class="dayPnl(day.settled)! >= 0 ? 'up' : 'down'">
                        {{ dayPnl(day.settled)! >= 0 ? '+' : '' }}{{ fmtMoney(dayPnl(day.settled)) }}
                      </span>
                    </div>
                    <div class="settle__grid">
                      <div class="cell"><span class="cell__k">净值</span>
                        <span class="cell__v">{{ day.settled.nav != null ? Number(day.settled.nav).toFixed(4) : '—' }}</span></div>
                      <div class="cell"><span class="cell__k">总资产</span>
                        <span class="cell__v">{{ fmtMoney(day.settled.total_assets) }}</span></div>
                      <div class="cell"><span class="cell__k">可用资金</span>
                        <span class="cell__v">{{ fmtMoney(day.settled.balance) }}</span></div>
                      <div class="cell"><span class="cell__k">持仓</span>
                        <span class="cell__v">{{ day.settled.positions ?? 0 }} 只</span></div>
                    </div>
                    <div v-if="day.settled.plan.length" class="orders">
                      <div v-for="(o, i) in day.settled.plan" :key="i" class="order">
                        <span class="order__side" :class="o.side === 'buy' ? 'up' : 'down'">{{ o.side === 'buy' ? '买入' : '卖出' }}</span>
                        <span class="order__name">{{ o.name || o.code }}</span>
                        <span class="order__qty">{{ o.qty }} 股</span>
                        <span class="order__res" :class="(day.settled.executions || [])[i]?.ok ? 'ok' : 'bad'">
                          {{ (day.settled.executions || [])[i]?.detail || '未成交' }}
                        </span>
                      </div>
                    </div>
                    <div v-else class="orders orders--none">当日无委托 · 保持现状</div>
                    <div v-if="day.protection?.length" class="orders orders--forced">
                      <span class="order__side down">系统保护</span>
                      <span v-for="(o, i) in day.protection" :key="'pr' + i" class="order__name">
                        {{ o.name || o.code }} · {{ o.detail || o.reason || '兜底止损' }}</span>
                    </div>
                    <div v-if="day.outlook" class="sec">
                    <div class="sec__label">次日预测</div>
                    <p class="sec__text">
                      {{ day.outlook.direction === 'up' ? '看涨' : day.outlook.direction === 'down' ? '看跌' : '看平' }}
                      <b class="num">{{ day.outlook.confidence }}%</b>
                      <template v-if="day.outlook_score">
                        · 实际
                        <b :class="(day.outlook_score.actual_pct || 0) >= 0 ? 'up' : 'down'">
                          {{ day.outlook_score.actual_pct }}%
                        </b>
                        · <b :class="day.outlook_score.hit ? 'down' : 'up'">{{ day.outlook_score.hit ? '命中' : '未中' }}</b>
                      </template>
                      <template v-if="day.outlook.reason"> · {{ day.outlook.reason }}</template>
                    </p>
                  </div>
                  <div v-if="day.expired?.length" class="rejects">
                      <div class="block__title">挂单超时（系统自动撤销）</div>
                      <div v-for="(x, i) in day.expired" :key="'ex' + i" class="rejrow">
                        <span class="rejrow__code">{{ x.side === 'buy' ? '买入' : '卖出' }} {{ x.code }} {{ x.qty }}股</span>
                        <span class="rejrow__msg">{{ x.detail || ('挂了 ' + (x.days || 0) + ' 个交易日未成交') }}</span>
                      </div>
                    </div>
                    <div v-if="day.rejections?.length" class="rejects">
                      <div class="block__title">被纪律规则拦截的委托（系统强制拒绝）</div>
                      <div v-for="(r, i) in day.rejections" :key="'rj' + i" class="rejrow">
                        <span class="rejrow__code">{{ r.side === 'buy' ? '买入' : '卖出' }} {{ r.code }} {{ r.qty }}股</span>
                        <span class="rejrow__msg">{{ r.message }}</span>
                      </div>
                    </div>
                    <div v-if="(day.settled.positions_detail || []).length" class="pos">
                      <span class="cell__k">持仓明细</span>
                      <div class="pos__list">
                        <span v-for="p in day.settled.positions_detail" :key="p.code" class="pos__item">
                          {{ p.name || p.code }} {{ p.qty }}股
                          <b v-if="p.pnl_pct != null" :class="p.pnl_pct >= 0 ? 'up' : 'down'">{{ fmtPct(p.pnl_pct * 100) }}</b>
                        </span>
                      </div>
                    </div>
                  </div>

                  <!-- 自我复盘（按真实战绩自省，写入长期记忆 + 纪律规则） -->
                  <div v-if="day.review" class="review">
                    <div class="review__head">
                      <Icon name="sparkles" :size="13" />
                      <span>自我复盘</span>
                      <span class="tmeta tmeta--r">{{ day.review.trigger || '按真实战绩自省' }} · 已写入长期记忆</span>
                    </div>
                    <p v-if="day.review.self_critique" class="review__text">{{ day.review.self_critique }}</p>
                    <ul v-if="day.review.lessons?.length" class="review__lessons">
                      <li v-for="(l, i) in day.review.lessons" :key="i">{{ l }}</li>
                    </ul>
                    <p v-if="day.review.style" class="review__style">风格更新：{{ day.review.style }}</p>
                    <div v-if="day.review.rules?.length" class="review__rules">
                      <span class="tmeta">已生效的纪律规则（交易系统强制）</span>
                      <span v-for="(r, i) in day.review.rules" :key="i" class="ruletag">{{ fmtRule(r) }}</span>
                    </div>
                  </div>

                  <!-- 选股依据 · 候选池（可审计，默认折叠） -->
                  <div v-for="c in candsOf(day.candidates)" :key="c.as_of || 'cand'" class="cands">
                    <div class="tools__head" @click="toggleNode('c:' + day.date, false)">
                      <Icon :name="isOpen('c:' + day.date, false) ? 'chevron-down' : 'chevron-right'" :size="13" class="chev" />
                      <span>选股依据 · 候选池 {{ candCount(c) }} 只</span>
                      <span class="tmeta tmeta--r">基准日 {{ c.as_of || '—' }} · 展开看来源与打分</span>
                    </div>
                    <div v-show="isOpen('c:' + day.date, false)" class="cands__body">
                      <CandDetail :cands="c" :picked="pickedSet(day.settled?.plan)" />
                    </div>
                  </div>

                  <!-- 工具调用（默认折叠） -->
                  <div v-if="day.tools.length" class="tools">
                    <div class="tools__head" @click="toggleNode('t:' + day.date, false)">
                      <Icon :name="isOpen('t:' + day.date, false) ? 'chevron-down' : 'chevron-right'" :size="13" class="chev" />
                      <span>工具调用 {{ day.tools.length }} 次</span>
                      <span class="tmeta tmeta--r">展开可查看入参</span>
                    </div>
                    <div v-show="isOpen('t:' + day.date, false)" class="tools__list">
                      <div v-for="(t, i) in day.tools" :key="i" class="tool">
                        <div class="tool__head" @click="toggleNode('tc:' + day.date + ':' + i, false)">
                          <Icon :name="isOpen('tc:' + day.date + ':' + i, false) ? 'chevron-down' : 'chevron-right'" :size="12" class="chev" />
                          <span class="tool__name">{{ toolLabel(t.name) }}</span>
                          <span class="tool__args">{{ toolArgs(t) }}</span>
                          <span v-if="t.result !== undefined" class="tool__res" :class="t.ok ? 'ok' : 'bad'">{{ t.result }}</span>
                        </div>
                        <pre v-show="isOpen('tc:' + day.date + ':' + i, false)" class="tool__json">{{ prettyArgs(t) }}</pre>
                      </div>
                    </div>
                  </div>

                  <div class="day-sep">
                    <span>{{ liveActive && day.date === liveDays[liveDays.length - 1]?.date ? '下一日 …' : '下一天' }}</span>
                  </div>                </div>
              </div>
            </div>
          </div>
          <div v-if="!liveDays.length" class="muted">等待第一天开始…</div>
        </div>
      </SectionCard>

      <SectionCard title="回放净值" desc="无前视逐日模拟的账户净值（1.0 = 起始）">
        <div ref="chartEl" class="chart" />
      </SectionCard>

      <SectionCard title="逐日回放" :desc="`共 ${current.decisions.length} 个交易日 · 按月份 / 日期折叠`" :padded="false">
        <template #actions>
          <button class="mini-btn" @click="expandAllHist">展开全部</button>
          <button class="mini-btn" @click="collapseAllHist">折叠全部</button>
        </template>
        <div class="days">
          <template v-for="hm in histMonths" :key="hm.month">
            <div class="mhead" @click="toggleHistMonth(hm.month)">
              <Icon :name="histMonthOpen(hm.month) ? 'chevron-down' : 'chevron-right'" :size="14" class="chev" />
              <span class="mhead__label">{{ hm.month }}</span>
              <span class="mhead__meta">{{ hm.items.length }} 个交易日
                <span class="mhead__range">{{ rangeHint(hm.items.map((d) => d.trade_date)) }}</span>
              </span>
            </div>
            <template v-if="histMonthOpen(hm.month)">
          <div v-for="d in hm.items" :key="d.id" class="day">
            <div class="day__head" @click="toggleHistDay(d)">
              <span class="day__date">{{ d.trade_date }}</span>
              <span class="tag" :class="d.plan?.length ? 'tag--act' : 'tag--hold'">{{ actionSummary(d) }}</span>
              <span class="day__nav" :class="(dayNav(d) ?? 1) >= 1 ? 'up' : 'down'">
                {{ dayNav(d) != null ? fmtPct((dayNav(d)! - 1) * 100) : '—' }}
              </span>
              <span class="day__status" :class="d.status">{{ d.status === 'done' ? '已完成' : d.status === 'error' ? '失败' : d.status }}</span>
              <Icon class="day__chev" :name="histDayOpen(d) ? 'chevron-down' : 'chevron-right'" :size="14" />
            </div>

            <div v-if="histDayOpen(d)" class="day__body">
              <div class="grid2">
                <div class="block">
                  <div class="block__title">思考过程</div>
                  <p class="prose">{{ d.thinking || '—' }}</p>
                  <p v-if="d.reflection" class="prose prose--sub">复盘：{{ d.reflection }}</p>
                </div>
                <div class="block">
                  <div class="block__title">当日委托与账户</div>
                  <table class="mini">
                    <thead><tr><th>股票</th><th>方向</th><th class="ta-r">数量</th><th class="ta-r">价格</th><th>结果</th></tr></thead>
                    <tbody>
                      <tr v-for="(o, i) in d.plan" :key="i">
                        <td>{{ o.name || o.code }}</td>
                        <td :class="o.side === 'buy' ? 'up' : 'down'">{{ o.side === 'buy' ? '买入' : '卖出' }}</td>
                        <td class="ta-r">{{ o.qty }}</td>
                        <td class="ta-r">{{ (d.executions || [])[i]?.price || o.price || '市价' }}</td>
                        <td><span :class="(d.executions || [])[i]?.ok ? 'ok' : 'bad'">{{ (d.executions || [])[i]?.detail || '未执行' }}</span></td>
                      </tr>
                      <tr v-if="!d.plan?.length"><td colspan="5" class="muted">当日无操作</td></tr>
                    </tbody>
                  </table>
                  <div class="acct">
                    <span>总资产 {{ fmtMoney(d.total_assets_after) }}</span>
                    <span>持仓 {{ (((d.context as Record<string, unknown>)?.positions as unknown[]) || []).length }} 只</span>
                  </div>
                  <div v-if="d.expired?.length" class="rejects">
                    <div class="block__title">挂单超时（系统自动撤销）</div>
                    <div v-for="(x, i) in d.expired" :key="'ex' + i" class="rejrow">
                      <span class="rejrow__code">{{ x.side === 'buy' ? '买入' : '卖出' }} {{ x.code }} {{ x.qty }}股</span>
                      <span class="rejrow__msg">{{ x.detail || ('挂了 ' + (x.days || 0) + ' 个交易日未成交') }}</span>
                    </div>
                  </div>
                  <div v-if="d.rejections?.length" class="rejects">
                    <div class="block__title">被纪律规则拦截的委托（系统强制拒绝）</div>
                    <div v-for="(r, i) in d.rejections" :key="i" class="rejrow">
                      <span class="rejrow__code">{{ r.side === 'buy' ? '买入' : '卖出' }} {{ r.code }} {{ r.qty }}股</span>
                      <span class="rejrow__msg">{{ r.message || r.code }}</span>
                    </div>
                  </div>
                </div>
              </div>

              <div v-if="reviewFilled(d.review)" class="review">
                <div class="review__head">
                  <Icon name="sparkles" :size="13" />
                  <span>自我复盘</span>
                  <span class="tmeta tmeta--r">按真实战绩自省 · 已写入长期记忆</span>
                </div>
                <p v-if="d.review?.self_critique" class="review__text">{{ d.review.self_critique }}</p>
                <ul v-if="d.review?.lessons?.length" class="review__lessons">
                  <li v-for="(l, i) in d.review.lessons" :key="i">{{ l }}</li>
                </ul>
                <p v-if="d.review?.style" class="review__style">风格更新：{{ d.review.style }}</p>
                <div v-if="d.review?.rules?.length" class="review__rules">
                  <span class="tmeta">已生效的纪律规则（交易系统强制）</span>
                  <span v-for="(r, i) in d.review.rules" :key="i" class="ruletag">{{ fmtRule(r) }}</span>
                </div>
              </div>

              <div v-for="c in candsOf(d.candidates)" :key="'hc' + d.id" class="cands">
                <div class="block__title" @click="toggleCand(d)">
                  <Icon :name="expanded['cd' + d.id] ? 'chevron-down' : 'chevron-right'" :size="13" class="chev" />
                  <span>选股依据 · 候选池 {{ candCount(c) }} 只</span>
                  <span class="cmeta">基准日 {{ c.as_of || '—' }}（当时的候选池与打分原文）</span>
                </div>
                <div v-if="expanded['cd' + d.id]" class="cands__body">
                  <CandDetail :cands="c" :picked="pickedSet(d.plan)" compact />
                </div>
              </div>

              <div v-if="dayCodes(d).length" class="kline">
                <div class="block__title">当日相关个股走势（截至 {{ d.trade_date }}）</div>
                <div v-for="c in dayCodes(d)" :key="c" class="kline__item">
                  <div class="kline__code">{{ c }}</div>
                  <div v-if="klineLoading[c + '@' + d.trade_date]" class="muted">加载中…</div>
                  <KlineChart
                    v-else-if="klineBars[c + '@' + d.trade_date]?.length"
                    :bars="klineBars[c + '@' + d.trade_date]"
                    :markers="markersFor(d)"
                    :height="260" :mas="[5, 20]"
                    :limit-pct="limitPctFor(c)"
                    :key="c + '@' + d.trade_date"
                  />
                  <div v-else class="muted" @click="loadKline(c, d.trade_date)">点击加载 K 线</div>
                </div>
              </div>
            </div>
          </div>
            </template>
          </template>
        </div>
      </SectionCard>
    </template>

    <!-- 新建回放 -->
    <Drawer :open="drawerOpen" title="新建回放" desc="让某个交易员在过去的数据里逐日模拟（无前视）" :width="440" @update:open="drawerOpen = $event">
      <div class="form">
        <FormField label="按哪个交易员回放" hint="沿用它的模型、本金与交易规则">
          <select v-model="draft.source_profile_id" class="ui-select">
            <option v-for="t in liveTraders" :key="t.id" :value="t.id">{{ t.name }}（{{ t.model || '默认模型' }}）</option>
          </select>
        </FormField>
        <FormField label="起始日期" hint="从该日起的交易日开始（历史新闻不可回溯）">
          <input v-model="draft.start_date" class="ui-input" type="date" />
        </FormField>
        <FormField label="本次天数" hint="单次最多 30 个交易日，可后续继续">
          <input v-model.number="draft.days" class="ui-input" type="number" min="1" max="30" />
        </FormField>
        <div class="note">
          回放从空记忆开始，逐日给模型「截至当日」的行情/候选/持仓，按当日价成交并结算。
          模型训练数据可能记得那段历史，这是 LLM 回测无法完全消除的局限。
        </div>
        <div class="form__foot">
          <button class="ui-btn" @click="drawerOpen = false">取消</button>
          <button class="ui-btn ui-btn--primary" :disabled="creating" @click="create">{{ creating ? '创建中…' : '开始回放' }}</button>
        </div>
      </div>
    </Drawer>
  </div>
</template>

<style scoped>
.replay { display: flex; flex-direction: column; gap: var(--sp-4); }
.bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-3);
  /* 吸顶：决策流很长时也能随时切换/继续回放 */
  position: sticky;
  top: calc(var(--sp-5) * -1);
  z-index: 30;
  margin: calc(var(--sp-5) * -1) calc(var(--sp-5) * -1) 0;
  padding: var(--sp-3) var(--sp-5);
  background: var(--glass);
  backdrop-filter: blur(14px) saturate(1.2);
  -webkit-backdrop-filter: blur(14px) saturate(1.2);
  border-bottom: 1px solid var(--glass-border);
}
.bar__left { display: flex; align-items: center; gap: var(--sp-3); }
.running { font-size: var(--fs-xs); color: var(--accent); }
/* .metrics 已收敛到全局样式（styles/base.css） */
.actions { display: flex; align-items: center; gap: var(--sp-2); flex-wrap: wrap; }
.src { font-size: var(--fs-sm); color: var(--text-sub); margin-right: auto; }
.chart { width: 100%; height: 300px; }
/* 折叠树：月份/日期/内容三层，用左侧导轨表达层级，行高收紧 */
.tnode { position: relative; }
.tbody { position: relative; margin-left: var(--sp-4); }
.tbody::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 4px;
  width: 1px;
  background: linear-gradient(180deg, var(--border), transparent 92%);
  pointer-events: none;
}
.thead--m {
  padding: var(--sp-2) var(--sp-3);
  border-radius: var(--radius-sm);
  font-weight: 600;
}
.thead--m:hover { background: var(--bg-hover); }
.thead--d {
  padding: 7px var(--sp-3);
  border-radius: var(--radius-sm);
}
.thead--d:hover { background: var(--bg-hover); }
.tlabel { font-variant-numeric: tabular-nums; }
.tlabel--m { font-size: var(--fs-md); letter-spacing: 0.02em; }
.tmeta { font-size: var(--fs-xs); color: var(--text-faint); }
.tmeta--dim { opacity: 0.7; }
.tmeta--r { margin-left: auto; }
.tstate {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: var(--radius-pill);
  background: var(--bg-overlay);
  color: var(--text-faint);
}
.tstate.running { background: var(--gold-dim); color: var(--gold); }
.tstate.done { background: color-mix(in srgb, var(--down) 14%, transparent); color: var(--down); }
.tbody--d { padding: var(--sp-1) 0 var(--sp-3); }
.sec { padding: var(--sp-2) 0; }
.sec__label,
.block__title {
  font-size: var(--fs-xs);
  font-weight: 600;
  letter-spacing: 0.06em;
  color: var(--text-faint);
  text-transform: none;
  margin-bottom: 4px;
}
.sec__text {
  margin: 0;
  font-size: var(--fs-md);
  line-height: 1.7;
  color: var(--text-sub);
  white-space: pre-wrap;
}
.dec {
  margin: var(--sp-2) 0;
  padding: var(--sp-3) var(--sp-4);
  border: 1px solid var(--border-soft);
  border-left: 2px solid var(--gold);
  border-radius: var(--radius-md);
  background: color-mix(in srgb, var(--bg-raised) 70%, transparent);
}
.dec__head {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: var(--fs-xs);
  font-weight: 600;
  color: var(--gold);
  margin-bottom: 5px;
}
.dec__text { margin: 0; font-size: var(--fs-md); line-height: 1.65; }
.dec__sub { margin: 6px 0 0; font-size: var(--fs-sm); color: var(--text-sub); }
.settle {
  margin-top: var(--sp-2);
  padding: var(--sp-3) var(--sp-4);
  border: 1px solid var(--border-soft);
  border-radius: var(--radius-md);
  background: var(--bg-panel);
}
.settle__grid,
.perf {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(96px, 1fr));
  gap: var(--sp-2);
  margin-top: var(--sp-2);
}
.cell {
  padding: 6px 8px;
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--bg) 45%, transparent);
}
.cell__k { font-size: 10px; color: var(--text-faint); display: block; }
.cell__v { font-family: var(--font-num); font-variant-numeric: tabular-nums; font-size: var(--fs-md); }
.order,
.rejrow {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  padding: 5px 8px;
  border-radius: var(--radius-sm);
  font-size: var(--fs-sm);
}
.order:nth-child(odd),
.rejrow:nth-child(odd) { background: color-mix(in srgb, var(--bg) 35%, transparent); }
.order__name,
.rejrow__code { font-weight: 500; }
.order__qty { color: var(--text-sub); }
.order__res { margin-left: auto; color: var(--text-faint); }
.order__res.ok { color: var(--down); }
.order__res.bad { color: var(--up); }
.orders--forced {
  border-left: 2px solid var(--up);
  padding-left: var(--sp-2);
  margin-top: 4px;
}
.pos__list { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 4px; }
.pos__item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border-radius: var(--radius-pill);
  background: var(--bg-overlay);
  font-size: var(--fs-xs);
  font-family: var(--font-num);
}
.days { display: flex; flex-direction: column; }
.day { border-bottom: 1px solid var(--border); }
.day:last-child { border-bottom: none; }
.day__head { display: flex; align-items: center; gap: var(--sp-3); padding: var(--sp-3) var(--sp-4); cursor: pointer; }
.day__head:hover { background: var(--panel-2); }
.day__date { font-variant-numeric: tabular-nums; font-size: var(--fs-sm); color: var(--text-sub); width: 92px; flex: none; }
.day__nav { font-size: var(--fs-xs); font-weight: 600; }
.day__status { font-size: var(--fs-xs); color: var(--text-faint); margin-left: auto; }
.day__status.error { color: var(--up); }
.day__chev { color: var(--text-faint); flex: none; }
.day__body { padding: 0 var(--sp-4) var(--sp-4); display: flex; flex-direction: column; gap: var(--sp-4); }
.grid2 { display: grid; grid-template-columns: 1.4fr 1fr; gap: var(--sp-4); }
@media (max-width: 1000px) { .grid2 { grid-template-columns: 1fr; } }
.block { display: flex; flex-direction: column; gap: 8px; }
.block__title { font-size: var(--fs-sm); font-weight: 600; color: var(--text-sub); }
.prose { font-size: var(--fs-sm); line-height: 1.7; color: var(--text); white-space: pre-wrap; margin: 0; }
.prose--sub { color: var(--text-sub); }
.mini { width: 100%; border-collapse: collapse; font-size: var(--fs-sm); }
.mini th { text-align: left; color: var(--text-faint); font-weight: 500; padding: 5px 8px; border-bottom: 1px solid var(--border); }
.mini td { padding: 6px 8px; border-bottom: 1px solid var(--border); }
.ta-r { text-align: right; }
.up { color: var(--up); }
.down { color: var(--down); }
.ok { color: var(--ok); }
.bad { color: var(--up); }
.muted { color: var(--text-faint); font-size: var(--fs-xs); }
.acct { display: flex; gap: var(--sp-4); font-size: var(--fs-xs); color: var(--text-sub); }
.tag { font-size: var(--fs-xs); padding: 2px 8px; border-radius: 999px; font-weight: 600; }
.tag--act { background: color-mix(in srgb, var(--accent) 16%, transparent); color: var(--accent); }
.tag--hold { background: var(--panel-2); color: var(--text-sub); }
.kline { display: flex; flex-direction: column; gap: var(--sp-2); }
.kline__item { border: 1px solid var(--border); border-radius: var(--radius-sm); overflow: hidden; }
.kline__code { font-size: var(--fs-xs); color: var(--accent); padding: 6px 10px; }
.form { display: flex; flex-direction: column; gap: var(--sp-4); }
.form__foot { display: flex; justify-content: flex-end; gap: var(--sp-2); }
.note { font-size: var(--fs-xs); color: var(--text-faint); line-height: 1.7; padding: var(--sp-3); background: var(--panel-2); border-radius: var(--radius-sm); }
.live-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--text-faint); }
.live-dot.is-on { background: var(--ok); animation: pulse 1.2s infinite; }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.35; } }
.live-state { font-size: var(--fs-xs); color: var(--text-sub); }
.mini-btn { font-size: var(--fs-xs); color: var(--text-sub); padding: 2px 8px; border: 1px solid var(--border); border-radius: 999px; background: transparent; cursor: pointer; }
.mini-btn:hover { color: var(--text); border-color: var(--text-faint); }
.live { display: flex; flex-direction: column; gap: 6px; max-height: 560px; overflow-y: auto; padding-right: 4px; }

/* 树状节点 */
.tnode { display: flex; flex-direction: column; }
.thead { display: flex; align-items: center; gap: 8px; padding: 7px 10px; cursor: pointer; border-radius: var(--radius-sm); user-select: none; }
.thead:hover { background: var(--panel-2); }
.thead--m { background: var(--panel-2); font-weight: 600; }
.thead--m .tlabel--m { font-size: var(--fs-sm); color: var(--text); }
.thead--d { border-left: 2px solid transparent; }
.thead--d:hover { border-left-color: var(--accent); }
.chev { color: var(--text-faint); flex: none; }
.tlabel { font-size: var(--fs-sm); color: var(--accent); font-variant-numeric: tabular-nums; font-weight: 700; }
.tmeta { font-size: var(--fs-xs); color: var(--text-faint); }
.tmeta--dim { color: var(--text-faint); opacity: .75; }
.tmeta--r { margin-left: auto; }
.tchip { font-size: var(--fs-xs); font-weight: 600; padding: 1px 8px; border-radius: 999px; background: var(--panel-2); }
.tchip.up { color: var(--up); }
.tchip.down { color: var(--down); }
.tstate { font-size: var(--fs-xs); padding: 1px 8px; border-radius: 999px; margin-left: 8px; }
.tstate.running { color: var(--accent); background: color-mix(in srgb, var(--accent) 14%, transparent); }
.tstate.settled { color: var(--ok); background: color-mix(in srgb, var(--ok) 12%, transparent); }
.tbody { display: flex; flex-direction: column; gap: 4px; padding-left: 14px; border-left: 1px dashed var(--border); margin-left: 12px; }
.tbody--d { gap: 10px; padding: 4px 0 8px 14px; }

/* 思考 / 决策 */
.sec { display: flex; flex-direction: column; gap: 4px; }
.sec__label { font-size: var(--fs-xs); font-weight: 600; color: var(--text-faint); letter-spacing: .04em; }
.sec__text { font-size: var(--fs-sm); line-height: 1.75; color: var(--text); white-space: pre-wrap; margin: 0; }
.dec { padding: var(--sp-3); background: var(--panel-2); border-radius: var(--radius-sm); border-left: 3px solid var(--accent); display: flex; flex-direction: column; gap: 6px; }
.dec__head { display: flex; align-items: center; gap: 6px; font-size: var(--fs-xs); font-weight: 700; color: var(--accent); }
.dec__text { font-size: var(--fs-sm); line-height: 1.75; color: var(--text); white-space: pre-wrap; margin: 0; }
.dec__sub { font-size: var(--fs-xs); line-height: 1.7; color: var(--text-sub); white-space: pre-wrap; margin: 0; }
.warn { display: flex; align-items: center; gap: 6px; font-size: var(--fs-xs); color: var(--accent); background: color-mix(in srgb, var(--accent) 10%, transparent); padding: 6px 10px; border-radius: var(--radius-sm); }

/* 当日结算卡片 */
.settle { border: 1px solid color-mix(in srgb, var(--ok) 35%, var(--border)); border-radius: var(--radius); background: color-mix(in srgb, var(--ok) 7%, transparent); overflow: hidden; }
.settle__top { display: flex; align-items: center; justify-content: space-between; padding: 10px 14px; background: color-mix(in srgb, var(--ok) 12%, transparent); }
.settle__tag { display: inline-flex; align-items: center; gap: 6px; font-size: var(--fs-xs); font-weight: 700; color: var(--ok); }
.settle__pnl { font-size: var(--fs-sm); font-weight: 700; font-variant-numeric: tabular-nums; }
.settle__grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 1px; background: var(--border); }
.settle__grid .cell { display: flex; flex-direction: column; gap: 3px; padding: 10px 14px; background: var(--panel); }
.cell__k { font-size: var(--fs-xs); color: var(--text-faint); }
.cell__v { font-size: var(--fs-sm); font-weight: 600; color: var(--text); font-variant-numeric: tabular-nums; }
.orders { display: flex; flex-direction: column; gap: 1px; background: var(--border); }
.orders--none { padding: 10px 14px; font-size: var(--fs-xs); color: var(--text-faint); background: var(--panel); }
.orders--forced { flex-direction: row; flex-wrap: wrap; align-items: center; gap: 10px; padding: 10px 14px;
  background: var(--panel); font-size: var(--fs-xs); border-left: 3px solid color-mix(in srgb, var(--down, var(--ok)) 55%, transparent); }
.orders--forced .order__name { color: var(--text-sub); }
.order { display: flex; align-items: center; gap: 10px; padding: 9px 14px; background: var(--panel); font-size: var(--fs-xs); }
.order__side { font-weight: 700; }
.order__name { color: var(--text); font-weight: 600; }
.order__qty { color: var(--text-sub); }
.order__res { margin-left: auto; }
.pos { display: flex; align-items: flex-start; gap: 10px; padding: 10px 14px; background: var(--panel); }
.pos__list { display: flex; flex-wrap: wrap; gap: 6px 14px; }
.pos__item { font-size: var(--fs-xs); color: var(--text-sub); }
.pos__item b { font-weight: 700; margin-left: 4px; }

/* 工具调用 */
.tools { display: flex; flex-direction: column; }
.cands { display: flex; flex-direction: column; gap: 6px; }
.cands__body { padding: 8px 10px 10px 18px; background: var(--panel-2); border-radius: var(--radius-sm); }
.cmeta { font-size: var(--fs-xs); color: var(--text-faint); margin-left: 8px; }
.review { padding: var(--sp-3); background: var(--panel-2); border-radius: var(--radius-sm); border-left: 3px solid color-mix(in srgb, var(--accent) 60%, var(--border)); display: flex; flex-direction: column; gap: 6px; }
.review__head { display: flex; align-items: center; gap: 6px; font-size: var(--fs-xs); font-weight: 700; color: var(--accent); }
.review__text { font-size: var(--fs-sm); line-height: 1.75; color: var(--text); margin: 0; white-space: pre-wrap; }
.review__lessons { margin: 0; padding-left: 18px; display: flex; flex-direction: column; gap: 3px; }
.review__lessons li { font-size: var(--fs-xs); line-height: 1.7; color: var(--text-sub); }
.review__style { font-size: var(--fs-xs); line-height: 1.7; color: var(--text-sub); margin: 0; }
.perf { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 1px; background: var(--border); border-radius: var(--radius-sm); overflow: hidden; }
.perf .cell { display: flex; flex-direction: column; gap: 4px; padding: 10px 14px; background: var(--panel); }
.memlist { display: flex; flex-direction: column; gap: 4px; }
.memitem { display: flex; gap: 8px; font-size: var(--fs-xs); line-height: 1.7; color: var(--text-sub); }
.memitem .mk { flex: 0 0 52px; color: var(--accent); }
.memitem--rule .mk--rule { color: var(--warn, var(--accent)); }
.review__rules { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; padding-top: 2px; }
.ruletag { font-size: var(--fs-xs); line-height: 1.6; padding: 2px 8px; border-radius: 999px; background: color-mix(in srgb, var(--accent) 12%, transparent); color: var(--text-sub); border: 1px solid color-mix(in srgb, var(--accent) 28%, transparent); }
.rejects { margin-top: 10px; display: flex; flex-direction: column; gap: 4px; }
.rejrow { display: flex; gap: 8px; font-size: var(--fs-xs); line-height: 1.7; }
.rejrow__code { flex: 0 0 150px; color: var(--warn, var(--accent)); }
.rejrow__msg { color: var(--text-sub); }
.tools__head { display: flex; align-items: center; gap: 8px; padding: 6px 10px; cursor: pointer; border-radius: var(--radius-sm); font-size: var(--fs-xs); color: var(--text-sub); background: var(--panel-2); }
.tools__head:hover { color: var(--text); }
.tools__list { display: flex; flex-direction: column; gap: 2px; padding: 6px 0 0 18px; }
.tool { display: flex; flex-direction: column; }
.tool__head { display: flex; align-items: center; gap: 8px; padding: 5px 8px; cursor: pointer; border-radius: var(--radius-sm); font-size: var(--fs-xs); }
.tool__head:hover { background: var(--panel-2); }
.tool__name { font-weight: 600; color: var(--text); }
.tool__args { color: var(--text-faint); }
.tool__res { margin-left: auto; }
.tool__res.ok { color: var(--ok); }
.tool__res.bad { color: var(--up); }
.tool__json { margin: 2px 0 6px 26px; padding: 8px 10px; background: var(--panel-2); border-radius: var(--radius-sm); font-size: 11px; line-height: 1.5; color: var(--text-sub); overflow-x: auto; white-space: pre; }

.day-sep { display: flex; align-items: center; gap: var(--sp-3); color: var(--text-faint); font-size: var(--fs-xs); margin: 6px 0; }
.day-sep::before, .day-sep::after { content: ''; flex: 1; height: 1px; background: var(--border); }

/* 逐日回放月份头 */
.mhead { display: flex; align-items: center; gap: 8px; padding: 9px var(--sp-4); cursor: pointer; background: var(--panel-2); user-select: none; }
.mhead:hover { background: color-mix(in srgb, var(--accent) 8%, var(--panel-2)); }
.mhead__label { font-size: var(--fs-sm); font-weight: 700; color: var(--text); }
.mhead__meta { font-size: var(--fs-xs); color: var(--text-faint); margin-left: auto; display: inline-flex; gap: 8px; }
.mhead__range { color: var(--text-faint); opacity: .75; font-variant-numeric: tabular-nums; }
</style>
