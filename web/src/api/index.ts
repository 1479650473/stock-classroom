// Typed API surface for the SPA.
import { api, ApiError } from './client'
import type { JobHandle } from './client'
export type { JobHandle }

// ---- types ----
export interface AccountSummary {
  account_id: number
  name: string
  initial_capital: number
  balance: number
  frozen: number
  market_value: number
  total_assets: number
  total_profit: number
  total_profit_pct: number
  float_pnl: number
  positions: number
  pending_orders: number
  total_trades: number
  nav?: number[]
}

export interface StrategyInfo {
  name: string
  total_return?: number
  cagr?: number
  alpha?: number
  sharpe?: number
  max_drawdown?: number
  rebalances?: number
  holdings?: number
}

export interface IndexQuote {
  code: string
  name: string
  price: number
  change_pct: number
  volume?: number
  amount?: number
}

export interface OverviewData {
  accounts: AccountSummary[]
  strategy: StrategyInfo | null
  as_of: string
  market: IndexQuote[]
}

export interface Position {
  id: number
  account_id: number
  code: string
  name: string
  qty: number
  frozen_qty: number
  cost_price: number
  current_price: number
  market_value: number
  float_pnl: number
  last_buy_date: string
}

export interface Order {
  id: number
  account_id: number
  code: string
  name: string
  side: 'buy' | 'sell'
  order_type: 'market' | 'limit'
  price: number
  qty: number
  filled_qty: number
  filled_price: number | null
  status: string
  commission: number
  stamp_tax: number
  created_at: string
  updated_at: string
}

export interface KlineBar {
  code: string
  date: string
  open: number
  high: number
  low: number
  close: number
  volume: number
  amount?: number
  turnover?: number
  ma5?: number | null
  ma10?: number | null
  ma20?: number | null
  ma60?: number | null
  dif?: number | null
  dea?: number | null
  macd?: number | null
  rsi6?: number | null
  rsi14?: number | null
  boll_mid?: number | null
  boll_upper?: number | null
  boll_lower?: number | null
}

export interface MinuteBar {
  time: string          // "YYYY-MM-DD HH:MM:SS"
  open: number
  high: number
  low: number
  close: number
  volume: number
  amount: number
}
export interface MinuteKline {
  bars: MinuteBar[]
  prev_close: number | null
  period: string
  source: string
}
/** 分钟级 K 线（1/5/15/30/60 分钟；新浪源，后端 45s 缓存） */
export const getKlineMinute = (code: string, period: string, days = 0) =>
  api.get<MinuteKline>('/api/kline/minute', { code, period, days }, { ttl: 20_000 })

export interface AutoLine { label: string; p1: { time: string; price: number }; p2: { time: string; price: number }; current?: number; violations?: number }
export interface AutoLevel { price: number; role: 'support' | 'resistance'; n: number; strength?: number; dist_atr?: number | null; last_date?: string; label: string }
export interface AutoTrend {
  kind: 'up' | 'down' | 'range'; label?: string
  trend?: AutoLine | null; channel?: AutoLine | null
  range?: { top: number; bottom: number; from: string; to: string; width_atr?: number | null; label: string } | null
}
export interface AutoEvent { time: string; price: number; type: string; text: string }
export interface AutoPivot { i: number; date: string; price: number; kind: 'high' | 'low' }
export interface AutoSignal { i: number; date: string; kind: 'signal' | 'mdb' | 'mdt' | 'ioi'; dir: number; follow: string; text: string; breakout_prev5?: string }
export interface AutoBarsInfo {
  counts?: { signal_yes: number; signal_failed: number; mdb: number; mdt: number; ioi: number }
  leg?: { label?: string; count?: number; weak?: boolean; note?: string }
  window?: number; streak?: number
  last_signal?: { date: string; text: string; follow: string } | null
}
export interface AutoAnalysis {
  ok: boolean; reason?: string
  code: string; period: string; as_of: string; close: number; atr14: number | null
  pivots: AutoPivot[]; levels: AutoLevel[]; trend: AutoTrend; events: AutoEvent[]
  signals?: AutoSignal[]; bars_info?: AutoBarsInfo
  structure: Record<string, unknown>; notes: string[]
}
/** 程序自动画线 + 自动技术分析（摆动点/支撑阻力/趋势线通道/箱体/突破事件 + 中文解读） */
export const getKlineAnalysis = (code: string, period = 'daily', days = 250) =>
  api.get<AutoAnalysis>('/api/kline/analysis', { code, period, days }, { ttl: 120_000 })

export interface StockRef {
  code: string
  name: string
  status?: string
}

export interface PickItem {
  code: string
  name: string
  price: number
  change_pct: number
  volume: number
  score: number
  groups?: { id: string; name?: string; max_score?: number; score?: number; indicators?: unknown[] }[]
}

export interface Bootstrap {
  kline: { exists: boolean; max: string | null; rows: number | null }
  stock_list_rows: number
  cache: { exists: boolean; max: string | null; rows: number }
  fundamental: { exists: boolean; max: string | null; rows: number | null }
  needs_init: boolean
  settings: { theme: string; font_size: number }
  ai_configured: boolean
}

// ---- system ----
// TTL 说明：30~120s 内重复进入页面直接命中缓存，避免"切回来又转圈"；
// 需要最新数据时调用方传 { fresh: true }（页面的刷新按钮）。
const T_SYS = 120_000
const T_PAGE = 30_000
export const getBootstrap = (fresh = false) => api.get<Bootstrap>('/api/system/bootstrap', undefined, { ttl: T_SYS, fresh })
export const getHealth = () => api.get('/api/system/health')
export const getSettings = (fresh = false) =>
  api.get<Record<string, unknown>>('/api/system/settings', undefined, { ttl: 300_000, fresh })
export const saveSettings = (body: Record<string, unknown>) => api.post<Record<string, unknown>>('/api/system/settings', body)
export const testLlm = (agent: Record<string, unknown>) => api.post('/api/system/settings/test-llm', agent)

// ---- overview ----
export const getOverview = (fresh = false) => api.get<OverviewData>('/api/overview', undefined, { ttl: T_PAGE, fresh })

// ---- market ----
export const getIndices = (fresh = false) => api.get<IndexQuote[]>('/api/market/indices', undefined, { ttl: T_PAGE, fresh })
export const getSectors = (type = 'industry') =>
  api.get<Record<string, unknown>[]>('/api/market/sectors', { type }, { ttl: 120_000 })
export const getNorthFlow = (days = 30) =>
  api.get<Record<string, unknown>[]>('/api/market/north-flow', { days }, { ttl: 120_000 })
export const getNews = (code: string, limit = 20) => api.get<Record<string, unknown>[]>('/api/market/news', { code, limit })
export const getQuote = (codes: string[]) => api.get<IndexQuote[]>('/api/market/quote', { codes: codes.join(',') })

// ---- kline / stock ----
export type KlinePeriod = 'daily' | 'weekly' | 'monthly'
// K 线是较重的查询：同参数 60s 内复用（切 tab 来回不再打库）
export const getKline = (code: string, days = 250, period: KlinePeriod = 'daily') =>
  api.get<KlineBar[]>('/api/kline', { code, days, period }, { ttl: 60_000 })
export const getCyq = (code: string) => api.get<Record<string, unknown>[]>('/api/kline/cyq', { code })
export const searchStock = (q: string, signal?: AbortSignal) => api.get<StockRef[]>('/api/stock/search', { q }, { signal })

// ---- etf ----
export interface EtfRef { code: string; name: string; type: string; updated_at?: string }
export interface EtfCompareSeries { code: string; name: string; values: number[] }
export interface EtfCompare { dates: string[]; series: EtfCompareSeries[] }
export const getEtfList = (search = '', type = '') =>
  api.get<EtfRef[]>('/api/etf/list', { search, type }, { ttl: 300_000 })
export const getEtfKline = (code: string, days = 250) =>
  api.get<KlineBar[]>('/api/etf/kline', { code, days }, { ttl: 60_000 })
export const getEtfCompare = (codes: string[], days = 250) =>
  api.get<EtfCompare>('/api/etf/compare', { codes: codes.join(','), days })

// ---- fund flow ----
export interface FundFlowBar {
  date: string
  close: number
  change_pct: number
  main_net: number
  main_ratio: number
  super_net: number
  super_ratio: number
  large_net: number
  large_ratio: number
  medium_net: number
  medium_ratio: number
  small_net: number
  small_ratio: number
}
export const getFundFlow = (code: string, days = 250) =>
  api.get<FundFlowBar[]>('/api/fund-flow/kline', { code, days }, { ttl: 120_000 })

// ---- trade ----
export const listAccounts = () => api.get<AccountSummary[]>('/api/trade/accounts')
export const createAccount = (name: string, initial_capital: number) => api.post('/api/trade/accounts', { name, initial_capital })
export const renameAccount = (id: number, name: string) => api.post(`/api/trade/accounts/${id}/rename`, { name })
export const resetAccount = (id: number) => api.post(`/api/trade/accounts/${id}/reset`)
export const deleteAccount = (id: number) => api.del(`/api/trade/accounts/${id}`)
export const getAccountSummary = (id: number) => api.get<Record<string, unknown>>(`/api/trade/accounts/${id}/summary`)
export const getPositions = (id: number) => api.get<Position[]>(`/api/trade/accounts/${id}/positions`)
export const getOrders = (id: number, status?: string) => api.get<Order[]>(`/api/trade/accounts/${id}/orders`, { status, limit: 100 })
export const getTrades = (id: number) => api.get<Record<string, unknown>[]>(`/api/trade/accounts/${id}/trades`)
export const getNavHistory = (id: number) => api.get<{ nav: number[] }>(`/api/trade/accounts/${id}/nav`)
export const placeOrder = (body: { account_id: number; code: string; name?: string; side: 'buy' | 'sell'; order_type?: string; price?: number; qty: number }) =>
  api.post('/api/trade/orders', body)
export const cancelOrder = (id: number) => api.post(`/api/trade/orders/${id}/cancel`)
export const refreshPrices = (id: number) => api.post(`/api/trade/accounts/${id}/refresh-prices`)

// ---- picks ----
export const getPicks = (top = 20, fresh = false) =>
  api.get<{ items: PickItem[]; total: number; stale: boolean; ts: number }>('/api/picks', { top }, { ttl: T_PAGE, fresh })
export const runPicks = (force = true) => api.post<JobHandle>('/api/picks/run', { force })

// ---- research ----
export interface RegimeData {
  regime: string
  regime_cn: string
  score: Record<string, unknown>
  sys_risk: Record<string, unknown>
  suggest_strategy: string
  rotation: Record<string, unknown>
  as_of: string
}
export interface FactorDef { id: string; name: string; group: string; desc: string }
export interface StrategyDef { id: string; name: string; kind: string; factors: string[]; desc: string; rebalance_bars: number; top_k_pct: number }

export const getRegime = () => api.get<RegimeData>('/api/research/regime')
export const getFactors = () => api.get<FactorDef[]>('/api/research/factors')
export const getStrategies = () => api.get<StrategyDef[]>('/api/research/strategies')
export const computeMetrics = (nav: number[], bench?: number[]) => api.post<Record<string, number>>('/api/research/metrics', { nav, bench })
export const describeStrategy = (contract: Record<string, unknown>) => api.post<Record<string, unknown>>('/api/research/strategy/describe', contract)

// ---- research v2 (回测/因子研究/纸面盘/对比) ----
export interface BacktestResult {
  name: string
  dates: string[]
  nav: number[]
  metrics: {
    total_return?: number; cagr?: number; sharpe?: number; sortino?: number
    max_drawdown?: number; alpha?: number; beta?: number; gamma?: number
    win_rate?: number; profit_factor?: number; num_trades?: number; turnover_yearly?: number
  }
  turnover_avg?: number; rebalances?: number; final_holdings?: Record<string, number>
}
export interface FactorStudyResult {
  factor_id: string; ic?: number; icir?: number; ic_series?: number[]
  group_returns?: Record<string, number[]>; longShortCurve?: { time: string; net: number }[]
}
export interface CompareResult {
  strategies: Record<string, { metrics: Record<string, number>; nav: number[]; dates: string[] }>
  start: string; end?: string
}

export const runBacktest = (contract: Record<string, unknown>, start?: string, end?: string) =>
  api.post<JobHandle>('/api/research/backtest', { contract, start, end })
export const runStudy = (factor_id: string, opts?: Record<string, unknown>) =>
  api.post<JobHandle>('/api/research/study', { factor_id, ...opts })
export const runPaper = (hp?: number, top_k_pct?: number, fwd_start?: string) =>
  api.post<JobHandle>('/api/research/paper', { hp, top_k_pct, fwd_start })
export const runCompare = (start?: string, end?: string) =>
  api.post<JobHandle>('/api/research/compare', { start, end })

// ---- optimize (自主策略进化, 分阶段) ----
export interface OptimizeFamily {
  strategy_name: string
  metrics: Record<string, number>
  describe: { summary: string; buy_condition: string }
  factors: string[]
  rebalance_bars: number
  top_k_pct: number
  use_tilt: boolean
  total_return?: number
}
export interface OptimizeProposal {
  name: string; description: string; source: string; reason: string
  factors: string[]; base_weights: Record<string, number>
  top_k_pct: number; rebalance_bars: number; use_tilt: boolean
}
export const optimizeFamilies = (hp = 20) => api.post<JobHandle>('/api/optimize/families', { hp })
export const optimizePropose = (hp = 20, use_llm = true, families?: Record<string, unknown>, as_of?: string) =>
  api.post<JobHandle>('/api/optimize/propose', { hp, use_llm, families: families || {}, as_of })
export const optimizeBacktest = (hp: number, proposal: OptimizeProposal) =>
  api.post<JobHandle>('/api/optimize/backtest', { hp, proposal })
export const optimizeVerdict = (payload: Record<string, unknown>) =>
  api.post<JobHandle>('/api/optimize/verdict', payload)
export const optimizeAll = (payload: Record<string, unknown>) =>
  api.post<JobHandle>('/api/optimize/all', payload)

// ---- agentops ----
export interface ScanResult { code: string; triggered: boolean; price: number }
export interface DeepEntry { code: string; name: string; verdict: string; reason: string; confidence: number; news: unknown[] }
export interface PortfolioSnapshot {
  account_id: number; name: string; cash: number; total_assets: number;
  holdings: Record<string, number>; prices: Record<string, number>; current_weights: Record<string, number>
  suggested_trades?: { code: string; name: string; side: 'buy' | 'sell'; qty: number; price: number; reason: string; value: number }[]
}

export const scanEntry = (code: string, contract: Record<string, unknown>) => api.post<ScanResult>('/api/agentops/scan', { code, contract })
export const deepAnalyze = (candidates: string[]) => api.post<{ entries: DeepEntry[] }>('/api/agentops/deep', { candidates })
export const portfolioRebalance = (account_id: number) => api.post<PortfolioSnapshot>('/api/agentops/portfolio/rebalance', { account_id })
export const getAgentStrategies = () => api.get<StrategyDef[]>('/api/agentops/strategies')

// ---- agent chat (AI 操盘台, SSE tool-calling) ----
export interface AgentStreamEvent {
  type: string
  delta?: string
  id?: string
  name?: string
  args?: Record<string, unknown>
  ok?: boolean
  summary?: string
  message?: string
}
export const agentStream = (messages: { role: string; content: string }[], onEvent: (ev: AgentStreamEvent) => void, signal?: AbortSignal) => {
  const url = api.base + '/api/agent/chat'
  const ctrl = signal ? { signal } : undefined
  return fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages }),
    ...ctrl,
  }).then(async (resp) => {
    if (!resp.ok || !resp.body) throw new ApiError(0, 'stream_failed', '无法连接 Agent 服务')
    const reader = resp.body.getReader()
    const decoder = new TextDecoder()
    let buf = ''
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      let idx: number
      while ((idx = buf.indexOf('\n\n')) >= 0) {
        const frame = buf.slice(0, idx).replace(/^data:\s*/, '').trim()
        buf = buf.slice(idx + 2)
        if (!frame) continue
        try { onEvent(JSON.parse(frame)) } catch { /* skip malformed */ }
      }
    }
  })
}
export const getAgentHealth = () => api.get<{ llm_configured: boolean; model: string; tools: number }>('/api/agent/health')
export const getAgentTools = () => api.get<{ tools: string[] }>('/api/agent/tools')

// ---- scheduler (AI 定时自主交易) ----
export interface SchedulerConfig {
  enabled: boolean; at: string; use_llm: boolean; hp: number
  last_run?: string | null; last_finish?: string | null; last_job?: string | null
  log?: string
}
export const getScheduler = () => api.get<SchedulerConfig>('/api/scheduler')
export const saveScheduler = (body: Partial<SchedulerConfig>) => api.post<SchedulerConfig>('/api/scheduler', body)
export const schedulerRunNow = () => api.post<{ queued: boolean; reason?: string }>('/api/scheduler/run-now')

// ---- pipeline ----
export interface PipelineStatus { last_update: string | null; status: string; steps?: Record<string, unknown> }
export interface PipelineStats {
  stock_count: number; kline_rows: number; latest_date: string | null; db_size: string
  active_stocks: number
  tables?: Record<string, { rows: number | null; latest: string | null }>
}

export const triggerPipelineUpdate = (pool_only = false) => api.post<JobHandle>('/api/pipeline/update', { pool_only })
export const getPipelineStatus = () => api.get<PipelineStatus>('/api/pipeline/status')
export const getPipelineStats = () => api.get<PipelineStats>('/api/pipeline/stats')

// ---- trainer ----
export interface TrainerSnapshot {
  cursor: number; total_bars: number; progress: number; balance: number;
  floating_pnl: number; total_equity: number; realized_pnl: number; win_rate: number;
  open_orders: number; closed_orders: number; current_price: number; current_date: string
}

export const startTrainer = (code: string, days?: number, initial_balance?: number) =>
  api.post<{ session_id: number; code: string; total_bars: number; snapshot: TrainerSnapshot }>('/api/trainer/start', { code, days, initial_balance })
export const trainerStep = (sid: number) => api.post<{ snapshot: TrainerSnapshot; bar: Record<string, unknown> }>(`/api/trainer/${sid}/step`)
export const trainerStepBack = (sid: number) => api.post<{ snapshot: TrainerSnapshot; bar: Record<string, unknown> }>(`/api/trainer/${sid}/step-back`)
export const trainerGoto = (sid: number, idx: number) => api.post<{ snapshot: TrainerSnapshot; bar: Record<string, unknown> }>(`/api/trainer/${sid}/goto`, { idx })
export const trainerOrder = (sid: number, side: string, qty: number, stop_loss?: number, take_profit?: number) =>
  api.post<{ snapshot: TrainerSnapshot }>(`/api/trainer/${sid}/order`, { side, qty, stop_loss, take_profit })
export const trainerCancel = (sid: number, order_idx: number) => api.post<{ snapshot: TrainerSnapshot }>(`/api/trainer/${sid}/cancel`, { order_idx })
export const trainerBars = (sid: number) => api.get<KlineBar[]>(`/api/trainer/${sid}/bars`)
export const endTrainer = (sid: number) => api.del(`/api/trainer/${sid}`)

// ---- replay (策略回放器) ----
export interface ReplayStrategy {
  id: string; name: string; kind: 'single' | 'family'; desc: string
  contract: Record<string, unknown> | null
}
export interface ReplayEvent {
  index: number; date: string; kind: 'entry' | 'exit'; price: number
  reason?: string; qty?: number; pnl?: number; fee?: number
  gross_pnl?: number; net_pnl?: number
  entry_date?: string; entry_price?: number; hold_bars?: number
}
export interface ReplayDaily {
  i: number; date: string; close: number
  signal_buy: boolean; signal_sell: boolean; position: boolean
  qty: number; entry_price: number; entry_index: number
  cash: number; market_value: number; equity: number
  float_pnl: number; realized_pnl: number; cum_fee: number
}
export interface ReplayBar {
  date: string; open: number; high: number; low: number; close: number; volume: number
  ma5?: number | null; ma10?: number | null; ma20?: number | null; ma60?: number | null
}
export interface ReplayResult {
  code: string; contract_name: string
  bars: ReplayBar[]; daily: ReplayDaily[]; events: ReplayEvent[]
  holding_spans: number[][]
  context_bars?: ReplayBar[]
  metrics: {
    total_return: number; final_equity: number; initial_balance: number
    num_trades: number; win_rate: number; profit_factor: number
    cum_fee: number; realized_pnl: number; max_drawdown: number; final_cash: number
  }
}

export interface ReplayParams {
  start?: string; end?: string
  initial_balance?: number
  sizing_mode?: 'percent_of_equity' | 'fixed_capital' | 'fixed_qty'
  sizing_value?: number
  commission_rate?: number; min_commission?: number; stamp_tax_rate?: number
  slippage?: number
}

export const getReplayStrategies = () => api.get<ReplayStrategy[]>('/api/replay/strategies')
export const getReplay = (code: string, strategy: string, days = 2500, params: ReplayParams = {}) =>
  api.get<ReplayResult>('/api/replay', { code, strategy, days, ...params })

// ---- AI 操盘手 (长期自主 LLM 交易员) ----
export interface TraderOrder {
  code: string; name?: string; side: 'buy' | 'sell'
  order_type?: 'market' | 'limit'; price?: number; qty: number; reason?: string
}
export interface TraderExecution extends TraderOrder {
  ok: boolean; detail: string; commission?: number; stamp_tax?: number; order_id?: number
}
export interface TraderNewsItem { title: string; summary?: string; time?: string; url?: string }
export interface TraderStockNews { code: string; name: string; news: TraderNewsItem[] }
export interface TraderTrace { tool: string; args?: Record<string, unknown>; error?: string }
export interface TraderCandPick { rank: number; code: string; name: string; score: number; groups?: { name: string; weight?: number; score: number }[] }
export interface TraderCandidates {
  as_of?: string; chain?: string; universe?: string
  scorecard?: { name?: string; version?: string; data_window?: number; groups?: { id: string; name: string; weight: number }[] }
  filters?: { rule: string; on: boolean }[]
  stats?: Record<string, number>
  picks?: TraderCandPick[]
  events?: { code?: string; name?: string; reason?: string }[]
  hot_sectors?: string[]
  error?: string
}
export interface TraderReview {
  self_critique?: string; lessons?: string[]; style?: string
  rules?: { kind?: string; value?: number; regimes?: string[]; until?: string; reason?: string; text?: string }[]
  trigger?: string
  performance?: Record<string, unknown>
}
export interface TraderDecision {
  id: number; profile_id: number; trade_date: string; as_of?: string
  status: 'running' | 'done' | 'error' | 'skipped'; trigger: string
  thinking: string; reflection: string
  context: Record<string, unknown>
  candidates?: TraderCandidates
  review?: TraderReview
  news: { market?: TraderNewsItem[]; stocks?: TraderStockNews[] }
  plan: TraderOrder[]; executions: TraderExecution[]
  rejections?: { code?: string; side?: string; qty?: number; message?: string }[]
  /** 自洽性提示（说法 vs 动作，不阻塞） */
  coherence?: { level?: string; kind?: string; msg: string }[]
  /** 编号决策协议：系统闸门结论 + 给模型的协议文本 */
  gates?: { gates?: { id: string; title: string; kind: string; status: string; note?: string; facts?: Record<string, unknown> }[]; text?: string; summary?: Record<string, unknown> }
  /** 系统撤销的超时挂单（挂单超时规则） */
  expired?: { order_id?: number; code?: string; name?: string; side?: string; qty?: number; days?: number; detail?: string }[]
  trace: TraderTrace[]
  nav_before?: number; nav_after?: number
  total_assets_before?: number; total_assets_after?: number
  error?: string; created_at: string; finished_at?: string
}
export interface TraderMemory {
  id: number; profile_id: number; kind: string; code: string
  content: string; active: number; created_at: string; decision_id?: number
  /** 写下这条经验时的市场环境（牛/熊/震荡），用于按环境分桶检索 */
  regime?: string
}
export interface TraderReplayMeta {
  source_profile_id: number; source_name: string; start_date: string
  planned_days: number; cursor: string; done_days: number; status: string
  initial_capital: number; note?: string
}
export interface TraderProfile {
  id: number; name: string; account_id: number; persona: string
  model: string; kind?: string; meta?: TraderReplayMeta
  risk_rules: Record<string, unknown>; initial_capital: number
  auto_execute: number; enabled: number; created_at: string
  summary?: TraderSummary
}
export interface TraderSummary {
  initial_capital?: number; balance?: number; market_value?: number
  total_assets?: number; total_profit?: number; total_profit_pct?: number
  positions?: number; total_trades?: number
}
export interface TraderNavPoint { date: string; nav: number; total_assets: number }
export interface TraderOverview {
  as_of: string
  benchmark: { name: string; dates: string[]; values: number[] }
  traders: {
    profile_id: number; name: string; model: string; enabled: number
    created_at?: string; initial_capital?: number; summary?: TraderSummary
    nav: TraderNavPoint[]; nav_format: string
  }[]
}
export interface TraderState {
  profile: TraderProfile
  summary: AccountSummary
  today: string
  today_decision: TraderDecision | null
  latest_decision: TraderDecision | null
  memory_count: number
  llm_configured: boolean
  model: string
  default_model?: string
}

export const getTraderProfiles = () => api.get<{ items: TraderProfile[] }>('/api/trader/profiles')
export const createTraderProfile = (fields: { name: string; initial_capital: number; model?: string; persona?: string }) =>
  api.post<{ profile: TraderProfile; summary: TraderSummary }>('/api/trader/profiles', fields)
export const updateTraderProfile = (id: number, fields: Partial<TraderProfile>) =>
  api.post<{ profile: TraderProfile }>(`/api/trader/profiles/${id}`, fields)
export const deleteTraderProfile = (id: number) =>
  api.del<{ deleted: number }>(`/api/trader/profiles/${id}`)
export const getTraderOverview = () => api.get<TraderOverview>('/api/trader/overview', undefined, { ttl: 30_000 })

export interface TraderOutlookStats {
  n: number
  hit_rate: number | null
  brier: number | null
  baseline_hit: number
  /** 弃权（看不清）次数与占比：弃权不计命中，也不污染校准 */
  abstained?: number
  abstain_rate?: number | null
  /** 置信度校准报告（借鉴 Laya 的 temperature scaling） */
  calibration?: {
    n: number
    raw_ece: number | null
    calibrated_ece: number | null
    log_loss?: number | null
    log_loss_calibrated?: number | null
    temperature?: { a: number; b: number; n: number } | null
    reliability: { bin: string; n: number; claimed: number; actual: number }[]
    discrimination: { ok: boolean; low_bin_hit?: number; high_bin_hit?: number; spread?: number; note: string }
    gate: { ok: boolean; threshold?: number; n?: number; hit_rate?: number; baseline_hit?: number; lift?: number; note: string }
    note?: string
    error?: string
  }
  /** 排除"看平"的方向性命中率（更诚实：空仓天天预测"平"会虚高总命中率） */
  n_directional: number
  hit_rate_directional: number | null
  n_flat: number
  hit_rate_flat: number | null
  note?: string
  recent: {
    date: string
    actual: 'up' | 'down' | 'flat'
    actual_pct: number
    hit: boolean
    confidence: number
    predicted: 'up' | 'down' | 'flat'
    brier: number
    reason?: string
  }[]
  buckets: { label: string; n: number; hit_rate: number; avg_conf: number }[]
  by_direction: { direction: string; label: string; n: number; hit_rate: number }[]
}
/** 组合纸面盘（前向记录）：K=20/H=10 中盘域、每日 1/H 分仓、单边 10bp */
export interface PaperPortfolio {
  started: boolean
  hint?: string
  config?: Record<string, unknown>
  last_date?: string
  nav?: number
  total_return_pct?: number
  days?: number
  positions?: number
  created_at?: string
  history?: { date: string; nav: number; positions?: number; opened?: number; closed?: number }[]
  benchmark?: { code: string; name: string; nav: (number | null)[] }
  holdings?: { code: string; name?: string; qty: number; buy_dates?: string[] }[]
  log?: { date: string; opened?: string[]; closed?: string[]; nav?: number }[]
  recent?: unknown[]
}
export const getPaperPortfolio = (tag = '', fresh = false) =>
  api.get<PaperPortfolio>('/api/alpha/paper', tag ? { tag } : {}, { ttl: 60_000, fresh })

/** 小模型（System 1 横截面头）的样本外成绩 + 可选现场扫描 */
export interface Sys1XsecReport {
  meta: { codes: number; test_from: string; test_to: string; test_n: number; horizon: number; features: number }
  test: { base_rate: number; auc_calibrated: number; ece_raw: number; ece_calibrated: number }
  deciles: Record<string, { mean_excess_pct: number; positive_days_pct: number; n_days: number }>
  signal_rule?: { ranking_on?: string; top_minus_bottom_pct?: number
    bands?: Record<string, { mean_excess_pct: number; positive_days_pct: number | null; n_days: number }> }
  baseline_composite?: { mean_excess_pct: number; positive_days_pct: number }
  note?: string
  tag?: string
  scan?: { as_of?: string; universe?: string; rows?: { code: string; name?: string
    p_beat_pool: number; raw: number; pct_in_universe?: number; signal: string }[]
    note?: string; error?: string }
  hint?: string
}
/** 小模型（System 1）：池内横截面排序的样本外成绩；scan=true 时现场扫描流动性池（约 15~30s） */
export const getSys1Xsec = (scan = false, top = 20, tag = '', fresh = false) =>
  api.get<Sys1XsecReport>('/api/trader/sys1_xsec',
    { ...(tag ? { tag } : {}), ...(scan ? { scan: 1, top } : {}) },
    { ttl: scan ? 0 : 120_000, fresh })
/** 方向预测校准：每日"次日净值方向 + 置信度"的命中率和 Brier 分数 */
export const getTraderOutlook = (profile_id: number, days = 60) =>
  api.get<TraderOutlookStats>('/api/trader/outlook', { profile_id, days }, { ttl: 30_000 })
export const getTraderState = (profile_id?: number) =>
  api.get<TraderState>('/api/trader/state', { profile_id })
export const getTraderDecisions = (limit = 30, offset = 0, profile_id?: number) =>
  api.get<{ items: TraderDecision[] }>('/api/trader/decisions', { limit, offset, profile_id })
export const getTraderDecision = (date: string, profile_id?: number) =>
  api.get<TraderDecision>(`/api/trader/decision/${date}`, { profile_id })
export const getTraderMemory = (kind?: string, active = true, profile_id?: number) =>
  api.get<{ items: TraderMemory[] }>('/api/trader/memory', { kind, active: active ? 1 : 0, profile_id })
export const toggleTraderMemory = (id: number, active: boolean) =>
  api.post<{ id: number; active: boolean }>(`/api/trader/memory/${id}/toggle`, { active })
export const saveTraderProfile = (fields: Partial<TraderProfile>) =>
  api.post<{ profile: TraderProfile }>('/api/trader/profile', fields)
export const runTrader = (opts: { force?: boolean; dry_run?: boolean; profile_id?: number } = {}) =>
  api.post<JobHandle>('/api/trader/run', opts)
export const runTraderAll = (opts: { force?: boolean; dry_run?: boolean } = {}) =>
  api.post<JobHandle>('/api/trader/run-all', opts)

// ---- 纵向回放 ----
export interface TraderPerfClosed {
  code: string; name: string; buy_date: string; sell_date: string; hold_days: number
  qty: number; buy_price: number; sell_price: number; pnl: number; pnl_pct: number
}
export interface TraderPerformance {
  as_of?: string
  decision_days?: number
  trading?: {
    closed_count: number; win_count: number; lose_count: number; win_rate_pct: number
    total_realized_pnl: number; avg_win: number; avg_lose: number
    profit_loss_ratio: number | null; avg_hold_days: number
    worst_trade?: TraderPerfClosed; best_trade?: TraderPerfClosed
    current_streak?: { type: string; count: number }
  }
  nav?: {
    start: number; last: number; cum_return_pct: number; max_drawdown_pct: number
    best_day_pct: number; worst_day_pct: number; up_days: number; down_days: number
    day_win_rate_pct: number
  }
  open_positions?: { code: string; name: string; qty: number; cost_price: number; price: number; float_pnl: number; float_pnl_pct: number }[]
  recent_closed?: TraderPerfClosed[]
  review_prompt?: string
}
export interface TraderReplayDetail {
  profile: TraderProfile
  summary: TraderSummary
  nav: TraderNavPoint[]
  decisions: TraderDecision[]
  performance?: TraderPerformance
  memory?: TraderMemory[]
}
export const getTraderReplays = () => api.get<{ items: TraderProfile[] }>('/api/trader/replays')
export const createTraderReplay = (fields: {
  source_profile_id: number; start_date: string; days: number
  initial_capital?: number; model?: string
}) => api.post<{ profile: TraderProfile; job: JobHandle }>('/api/trader/replay', fields)
export const getTraderReplay = (id: number, limit = 60) =>
  api.get<TraderReplayDetail>(`/api/trader/replay/${id}`, { limit })
export const continueTraderReplay = (id: number, days = 30) =>
  api.post<{ job: JobHandle }>(`/api/trader/replay/${id}/continue`, { days })
export const distillTraderReplay = (id: number, target_profile_id: number) =>
  api.post<{ copied: number; target: string; kinds: string[] }>(
    `/api/trader/replay/${id}/distill`, { target_profile_id })
export const getTraderNews = (limit = 15) =>
  api.get<{ items: TraderNewsItem[] }>('/api/trader/news', { limit })

// ---- alpha（因子挖掘：公式搜索 + 回测奖励） ----
export interface AlphaFormula {
  id: number; run_id: number; fold?: number; rank: number
  tokens: string[]; formula: string
  train_metrics: Record<string, number>
  oos_metrics: Record<string, number>
  kept: number; created_at?: string
}
export interface AlphaRun {
  id: number; kind: 'mine' | 'walkforward'; status: 'running' | 'done' | 'error'
  params: Record<string, unknown>; meta: Record<string, number | string>
  summary: Record<string, unknown>; history?: number[]
  error?: string | null; created_at?: string; finished_at?: string
  formulas?: AlphaFormula[]
}
export interface AlphaZooRow {
  factor: string; ic: number; ic_ir: number; ic20: number; ic_neutral: number
  ex_ann: number; ex_neutral: number; ex_sortino: number; turnover: number
  maxdd: number; seg_ex: number[]; seg_pos: number; n_seg: number
}
export interface AlphaCompositeReport {
  meta: { components?: string[]; neutralized?: boolean; top_k?: number; hold?: number; [k: string]: unknown }
  full?: { ic?: number; ic_ir?: number; ann?: number; ex_ann?: number; ex_sortino?: number; maxdd?: number; turnover?: number }
  folds?: { fold: number; test: string; train_ex: number; oos_ex: number; oos_sortino: number; oos_ic: number; oos_dd: number }[]
  hint?: string
}
export const getAlphaZoo = (sort = 'ic', top = 200) =>
  api.get<{ meta: Record<string, unknown>; sort: string; factors: AlphaZooRow[]; hint?: string }>('/api/alpha/zoo', { sort, top })
export const getAlphaCompositeReport = () =>
  api.get<AlphaCompositeReport>('/api/alpha/composite_report')
export const getAlphaComposite = (date?: string, top = 12) =>
  api.get<Record<string, unknown>>('/api/alpha/composite', date ? { date, top } : { top })
export const getAlphaMeta = () =>
  api.get<{ defaults: Record<string, number | string>; features: string[]; operators: string[] }>('/api/alpha/meta')
export const startAlphaMine = (params: Record<string, unknown>) =>
  api.post<{ job: JobHandle }>('/api/alpha/mine', params)
export const startAlphaWalkforward = (params: Record<string, unknown>) =>
  api.post<{ job: JobHandle }>('/api/alpha/walkforward', params)
export const getAlphaRuns = (limit = 20, kind?: string) =>
  api.get<{ items: AlphaRun[] }>('/api/alpha/runs', kind ? { limit, kind } : { limit })
export const getAlphaRun = (id: number) => api.get<AlphaRun>(`/api/alpha/run/${id}`)

export interface AlphaSmbResult {
  meta?: Record<string, unknown>
  summary?: { ann?: number; sharpe?: number; maxdd?: number; month_win?: number; t_stat?: number; total?: number; months?: number }
  smb?: { mean_month?: number; ann?: number; t_stat?: number; win?: number; months?: number }
  cost_curve?: { cost_one_way: number; ann: number; sharpe: number; maxdd: number }[]
  variants?: { top: number; ann: number; sharpe: number; maxdd: number; month_win: number }[]
  tilt_compare?: { name: string; ann: number; sharpe: number; maxdd: number; month_win: number; t_stat: number }[]
  benchmark?: { ann?: number }
  recent_picks?: { month: string; codes: string[]; names: string[]; mv_yi: number[]; avg_mv_yi: number; next_ret: number }[]
  years?: { year: string; ret: number; months: number }[]
  comparison_no_bj?: {
    strategy?: { ann?: number; sharpe?: number; maxdd?: number; month_win?: number; t_stat?: number }
    smb?: { ann?: number; t_stat?: number }
    cost_curve?: { cost_one_way: number; ann: number }[]
    variants?: { top: number; ann: number; sharpe: number; maxdd: number; month_win: number }[]
    delta?: { ann?: number; sharpe?: number; ann_at_cost_0_3pct?: number }
  }
  hint?: string
}
export const getAlphaSmb = () => api.get<AlphaSmbResult>('/api/alpha/smb')

export interface AlphaAllocationLeg { spec: string; label: string; ann?: number; vol?: number; sharpe?: number; maxdd?: number; month_win?: number; months?: number }
export interface AlphaAllocationMix { name?: string; weights: number[]; ann?: number; vol?: number; sharpe?: number; maxdd?: number; month_win?: number }
export interface AlphaAllocation {
  legs: AlphaAllocationLeg[]
  months: string[]
  corr: number[][]
  weights?: Record<string, number[]>
  mixes: AlphaAllocationMix[]
  best?: AlphaAllocationMix
  best_equity?: number[]
  leg_equity?: Record<string, number[]>
  available?: { spec: string; label: string }[]
  rolling_os?: AlphaRollingOs | null
  meta: { start: string; end: string; n_months: number }
}
export interface AlphaRollingOs {
  window: number
  methods: Record<string, { ann?: number; vol?: number; sharpe?: number; maxdd?: number; month_win?: number; start?: string; end?: string; weights_last?: number[] }>
  bench?: Record<string, { ann?: number; vol?: number; sharpe?: number; maxdd?: number } | string>
}
export const getAlphaAllocation = (legs: string, grid = 0.05, rolling = true, window = 36) =>
  api.get<AlphaAllocation>('/api/alpha/allocation', { legs, grid, rolling: rolling ? 1 : 0, window })

// ---- 模拟盘（对接 stock-ml 项目快照） ----
export interface SimPosition { code: string; name?: string; leg?: string; shares: number; cost: number; price: number; value: number; ret_pct: number }
export interface SimTrade { date: string; leg?: string; code: string; side: string; shares: number; price: number; amount: number; fee: number; pnl_pct?: number }
export interface SimLeg { name: string; nav: number }
export interface SimAccount {
  name: string
  label: string
  init: number
  nav: number
  ret_pct: number
  cash: number
  mv: number
  positions: SimPosition[]
  trades: SimTrade[]
  nav_history: { date: string; nav: number }[]
  last_rebalance?: string
  strategy?: string
  legs?: SimLeg[]
}
export interface SimSnapshot { generated: string; data_date: string; accounts: SimAccount[] }
export const getSimAccounts = () => api.get<SimSnapshot>('/api/sim/accounts')
export const refreshSim = () => api.post<SimSnapshot>('/api/sim/refresh')

// ---- 基金套利（LOF 折溢价：场内价 vs 单位净值，含费率/门槛/成本拆解） ----
export interface ArbPlan {
  kind: 'premium' | 'discount'
  amount: number
  shares: number
  buy_fee?: number
  commission: number
  redeem_fee?: number
  redeem_rate_pct?: number
  tier_label?: string | null
  transfer_fee: number
  slippage_cost?: number
  gross_in: number
  net_back: number
  profit: number
  space_pct: number
  days: number
  annual_pct: number
  fee_pct: number
  costs?: number
  /** 覆盖手续费开始盈利的最小申购金额（元） */
  breakeven?: number | null
}
export interface ArbTier { min_days: number; max_days: number; rate_pct: number; label: string }
export interface ArbItem {
  code: string
  name: string
  exchange: string
  ftype?: string | null
  price: number
  price_date: string
  nav: number
  nav_date: string
  nav_lag_days: number | null
  lag_bars?: number
  aligned?: boolean
  price_latest_date?: string
  premium_pct: number
  direction: 'premium' | 'discount'
  amount?: number | null
  liquidity_ok: boolean
  purchase_status?: string | null
  redeem_status?: string | null
  min_amount?: number | null
  daily_limit?: number | null
  fee_rate_pct?: number | null
  is_qdii: boolean
  tags: string[]
  premium: ArbPlan
  discount: ArbPlan
  discount_best: ArbPlan
  space_pct: number
  profit_per_10k: number
  executable?: boolean
  space_best_pct?: number | null
  /** 本金上限提示：申购日限额 与 当日成交额×10% 取小 */
  max_amount?: number | null
}
export interface ArbList { total: number; cfg: Record<string, number>; items: ArbItem[] }
export interface ArbHistPoint { date: string; close: number; nav: number; nav_date: string; premium_pct: number }
export interface ArbDetail {
  code: string
  name: string
  exchange: string
  ftype?: string | null
  price: number
  price_date: string
  nav: number
  nav_date: string
  premium_pct: number | null
  amount?: number | null
  purchase_status?: string | null
  redeem_status?: string | null
  min_amount?: number | null
  daily_limit?: number | null
  fee_rate_pct?: number | null
  redeem_tiers: ArbTier[]
  buy_tiers: { amount: string; rate: string; rate_pct?: number | null }[]
  cfg: Record<string, number>
  history: ArbHistPoint[]
  nav_history: { date: string; nav: number }[]
  price_history: { date: string; close: number; amount?: number | null }[]
  plans: { premium?: ArbPlan; discount?: ArbPlan; discount_best?: ArbPlan }
  sizing?: {
    amount: number
    premium: { profit: number; space_pct: number; fee_pct: number }
    discount: { profit: number; space_pct: number; fee_pct: number }
  }[]
  max_amount?: number | null
  curve?: { premium: { amount: number; profit: number; space_pct: number; fee_pct: number }[]
            discount: { amount: number; profit: number; space_pct: number; fee_pct: number }[] }
  hist_arb?: {
    threshold: number; n: number; mean_pct: number; median_pct: number
    win_pct: number; premium_t: number; premium_t3: number | null
  }[]
  stats?: {
    n: number; median_pct: number; p90_pct: number; p10_pct: number
    max_pct: number; min_pct: number; days_above_1pct: number; days_above_2pct: number
  }
}
export interface ArbOverview {
  stats: Record<string, unknown>
  count: { all: number; premium: number; discount: number; premium_profitable: number; discount_profitable: number }
  top_premium: { code: string; name: string; premium_pct: number; space_pct: number; days: number; purchase_status?: string | null; tags: string[] }[]
  top_discount: { code: string; name: string; premium_pct: number; space_pct: number; days: number; tags: string[] }[]
}
export const getArbOverview = () => api.get<ArbOverview>('/api/fund-arb/overview')
export const getArbList = (params: Record<string, unknown>) => api.get<ArbList>('/api/fund-arb/list', params)
export const getArbDetail = (code: string, params: Record<string, unknown> = {}) =>
  api.get<ArbDetail>(`/api/fund-arb/fund/${code}`, params)
export const getArbStats = () => api.get<Record<string, unknown>>('/api/fund-arb/stats')
export const syncArb = (mode: 'daily' | 'fees' | 'backfill' | 'list' = 'daily') =>
  api.post<{ job: JobHandle; mode: string }>('/api/fund-arb/sync', { mode })

/* ─────────────────────── 实盘策略决策（pali）───────────────────────
 * 董事长 2026-10-17 定调：「开发软件要尽量为策略服务」。
 * 软件原先的「选股」是 `compute_factor_picks()` 全市场扫描，**与实盘无关**；
 * 这一组接口**只读**展示实盘策略真正的决策结果（决策 CSV + 排雷 JSON）。
 *
 * 口径：pred / ff20 / rank / 排雷 level **一律原样透传**，前端不加工、不换算。
 */

/** 排雷结论。NOT_CHECKED = 程序没跑它（正常）；UNKNOWN = 该查却没记录（异常） */
export type RiskLevel = 'PASS' | 'CAUTION' | 'REJECT' | 'UNKNOWN' | 'NOT_CHECKED'

export interface StrategyPick {
  code: string
  name: string
  industry: string
  /** 模型打分（原值，来自 decision CSV） */
  pred: number | null
  /** 20 日资金流 */
  ff20: number | null
  ff_ok: boolean
  rank: number | null
  board: string
  board_cn: string
  is_main_board: boolean
  risk_level: RiskLevel
  risk_level_cn: string
  risk_flags: string[]
  risk_reds: string[]
  risk_yels: string[]
  ann_total: number | null
  /** 被什么挡住（空 = 可买）*/
  blocked_by: string[]
  /** 策略硬约束判定：只主板 + 只买 PASS */
  buyable: boolean
}

export interface StrategyPoolInfo {
  /** 池目录名（如 test_pool100）。**不要假设规模是 100** —— 扩池后会变 */
  name: string | null
  path: string | null
  /** 池内股票数 */
  size: number
  /** 池与当日决策代码的交集数；< ranked 说明可能选错了池 */
  matched: number | null
  meta?: Record<string, unknown>
  /** 所有候选池（诊断用） */
  candidates?: { name: string; size: number; path: string; mtime: number }[]
  /** 当日实际被打分的只数（数据不全的票会被跳过，可能 < size） */
  ranked?: number
  skipped?: number
  /** 口径说明：rank 为池内排名 */
  scope_note?: string
}

export interface StrategyPicksResult {
  available: boolean
  reason?: string
  date: string | null
  source?: string
  total?: number
  /** 池边界（扩池后自动变化，前端不得写死） */
  pool?: StrategyPoolInfo
  /** Top20% 的实际门槛（扩池后自动变大，不要写死 20） */
  top20_threshold?: number
  /** checked = 有排雷记录的条数；depth = 排雷深度（pali --top N） */
  risk: { available: boolean; ts?: string | null; reason?: string; checked?: number; depth?: number }
  items: StrategyPick[]
  buyable_count?: number
  position: Record<string, unknown> | null
  /** 策略执行摘要（AUTO_LOG.md 的最近一段，人工可读） */
  summary?: { available: boolean; date?: string; lines?: string[]; reason?: string }
}

export const getStrategyPicks = (date?: string) =>
  api.get<StrategyPicksResult>('/api/strategy/picks', date ? { date } : undefined, { ttl: 0 })

export const getStrategyDates = () =>
  api.get<{ dates: string[] }>('/api/strategy/dates', undefined, { ttl: 0 })

export const getStrategyMeta = () =>
  api.get<Record<string, unknown>>('/api/strategy/meta', undefined, { ttl: 0 })

/* ─────────── 多日决策追踪 ───────────
 * 单日快照看不出趋势，但策略的续持/卖出判断依赖**跨日变化**
 * （跌出 Top20% 或 FF 转好）。这个接口补上那一层。
 *
 * 口径：只汇总真实存在的决策日期，**缺的日子留空不插值**。
 */
export interface StrategyTrendItem {
  code: string
  name: string
  industry: string
  /** 每日 rank；缺该日决策时为 null */
  ranks: Record<string, number | null>
  preds: Record<string, number | null>
  ff_ok: Record<string, boolean | null>
  rank_latest: number | null
  rank_first: number | null
  /** 最新 rank − 最早 rank；**负数 = 排名上升（更靠前）** */
  delta: number | null
  pred_latest: number | null
  pred_delta: number | null
  days_present: number
  in_top20: boolean
  threshold_latest: number | null
}

export interface StrategyTrendResult {
  available: boolean
  reason?: string
  /** 升序日期（YYYYMMDD） */
  dates: string[]
  /** 每日 Top20% 门槛（按当日实际打分只数算） */
  thresholds: Record<string, number>
  items: StrategyTrendItem[]
  total?: number
  note?: string
  source?: string
}

export const getStrategyTrend = (days = 5) =>
  api.get<StrategyTrendResult>('/api/strategy/trend', { days }, { ttl: 0 })

/* ─────────────────────── 实盘账户总览 ───────────────────────
 * 打开实盘页**立刻**能看到账户数据，不必先点"读取"。
 * 数据来自策略侧 AUTO_LOG.md 的**人工核对记录**（最可靠），并如实带出时间与来源；
 * 券商客户端可读时，前端再叠加一次实时读取。
 *
 * 口径纪律：每个数字都必须能追到"哪一天、什么来源"。陈旧就标陈旧。
 */
export interface LiveAccountCheck {
  ok: boolean
  formula?: string
  [k: string]: unknown
}

export interface LiveAccountEstimate {
  available: boolean
  reason?: string
  source?: string
  /** 该读数的日期（YYYY-MM-DD）—— 必须展示出来 */
  as_of?: string | null
  code?: string | null
  name?: string | null
  qty?: number | null
  cost?: number | null
  price?: number | null
  market_value?: number | null
  float_pnl?: number | null
  /** 当日盈亏（当天赚/亏多少），与"持仓浮盈"是两个不同指标 */
  day_pnl?: number | null
  /** 可用资金（后端字段名是 cash，不是 available —— 避免与布尔标志冲突） */
  cash?: number | null
  total_assets?: number | null
  /**
   * 盘中参照（当天较早一次完整读数，通常 09:35 的「核对」行）。
   * 主读数取的是**收盘/最新**状态，这个只用于对照"盘中 → 收盘"的变化。
   */
  intraday?: {
    market_value?: number | null
    float_pnl?: number | null
    total_assets?: number | null
    price?: number | null
    cash?: number | null
    raw?: string
  } | null
  carried_over?: boolean
  raw?: string
  candidates?: number
  /** 每个字段取自 AUTO_LOG 的哪一行（provenance，排查用） */
  field_sources?: Record<string, number>
  /** 算术自校验：把"能不能对上账"显式算出来，界面据此警示 */
  checks?: {
    assets_identity?: LiveAccountCheck
    pnl_identity?: LiveAccountCheck
  }
}

export interface LiveAccountHistoryItem {
  date: string
  total_assets: number | null
  market_value: number | null
  cash: number | null
  float_pnl: number | null
  day_pnl: number | null
  price: number | null
  qty: number | null
  code: string | null
  /** 当日读数是否通过恒等式校验；null = 当天没有足够字段可校验 */
  checks_ok: boolean | null
}

export interface LiveAccountHistory {
  available: boolean
  reason?: string
  items: LiveAccountHistoryItem[]
  /** 有核对记录的天数（**不是**连续交易日） */
  days: number
  range: [string, string] | null
  source?: string
  note?: string
}

export interface LiveAccountResult {
  estimate: LiveAccountEstimate
  /** 最新快照里的干净浮点字段（次选来源） */
  snapshot: { name?: string; ts?: string | null; funds_value?: number | null; max_buy_value?: number | null } | null
  /** 券商客户端当前是否可读（不可读时"刷新账户"必然失败） */
  readable: boolean
  last?: Record<string, unknown> | null
  ta_dir?: string
  /** 每日核对记录（升序）。只含真实存在记录的日期，未做插值补齐 */
  history?: LiveAccountHistory
}

export const getLiveAccount = () => api.get<LiveAccountResult>('/api/live/account', undefined, { ttl: 0 })

/* ─────────────────────────── 实盘（trade-automation 桥接） ───────────────────────────
 * 后端 backend/api/blueprints/live.py 把 C# 工具包成 HTTP。
 * 约定：返回的是**工具自己的产物**（last-result.json / 各 *.log），
 * 前端只做透传 + 类型标注，不"美化"结果 —— 失败原因要原样可见。
 */

/** 工具某次调用的统一返回形状 */
export interface LiveRun {
  ok: boolean
  exit_code: number | null
  /** 工具权威产物 last-result.json */
  result: {
    ts?: string
    command?: string
    action?: string
    process?: string
    parameters?: Record<string, unknown>
    ok?: boolean
    exit_code?: number
    message?: string
    popup_texts?: string[]
    screenshots?: string[]
    log_file?: string
  } | null
  stderr: string
  log_tail: string
  elapsed: number | null
  /** 桥接层自身错误（超时/找不到 exe），与工具错误分开 */
  error: string | null
  cmd: string[]
  submitted?: boolean
  mode?: string
}

export interface LiveStatus {
  available: boolean
  tool_dir: string
  ta_dir: string
  last: {
    ts?: string
    command?: string
    action?: string
    ok?: boolean
    exit_code?: number
    message?: string
    parameters?: Record<string, unknown>
  } | null
  files: Record<string, string | null>
  snapshots: string[]
  unlock: LiveUnlockState
  login_guard: { guarded: boolean; reason?: string | null; ts?: string | null; cred_hash?: string }
}

export const getLiveStatus = () => api.get<LiveStatus>('/api/live/status', undefined, { ttl: 0 })

/** 读券商客户端面板（只读）。bg=1 用后台模式，不抢前台焦点。 */
export const queryLivePanel = (panel: 'positions' | 'deals' | 'cancel' | 'funds', bg = true, timeout = 150) =>
  api.get<LiveRun>(`/api/live/query/${panel}`, { bg: bg ? 1 : 0, timeout }, { ttl: 0 })

/** 实时行情（现价/涨停/昨收/跌停）。 */
export const queryLiveQuote = (codes: string[], bg = true, timeout = 180) =>
  api.get<LiveRun>('/api/live/quote', { codes: codes.join(','), bg: bg ? 1 : 0, timeout }, { ttl: 0 })

/** 一键启动/登录客户端（有副作用，不下单）。 */
export const liveStartup = (credFile?: string, bg = true) =>
  api.post<LiveRun>('/api/live/startup', { cred_file: credFile, bg })

/** 收盘快照：确保就绪 → 读资金+持仓+成交+委托 → 存档。 */
export const liveSnapshot = (credFile?: string) =>
  api.post<LiveRun>('/api/live/snapshot', { cred_file: credFile })

/** 当日成交回传（对账）。 */
export const getLiveFills = (date?: string) =>
  api.get<{ date: string; count: number; fills: Record<string, unknown>[] }>(
    '/api/live/fills', date ? { date } : undefined, { ttl: 0 })

/** 幂等锁记录：已提交委托及其状态。 */
export const getLiveIdempotency = () =>
  api.get<{ entries: Record<string, unknown>[] }>('/api/live/idempotency', undefined, { ttl: 0 })

export const listLiveSnapshots = (limit = 30) =>
  api.get<{ snapshots: string[] }>('/api/live/snapshots', { limit }, { ttl: 0 })

/** 上次解锁尝试的结果。known=false 表示**未知**（不要当成"未锁定"）。 */
export interface LiveUnlockState {
  known: boolean
  ok: boolean | null
  ts?: string | null
  detail?: string | null
  log_tail?: string
}

export const getLiveSnapshot = (name: string) =>
  api.get<Record<string, unknown>>(`/api/live/snapshots/${encodeURIComponent(name)}`, undefined, { ttl: 0 })

/**
 * 解锁被（券商交易保护）锁定的交易界面。
 *
 * 与「首次登录」是**两条不同路径**：首次登录是顶层弹窗（账号+密码两个框），
 * 超时重锁是**嵌在主窗口里的对话框**（无标题、只有 1 个密码框），
 * `--logintest` 找不到它，所以单独走 `--unlock`。
 *
 * 安全约定（工具侧强制，本层不放松）：
 *  · 密码只从**凭据文件**读，绝不经过 HTTP 请求体
 *  · 键盘输入只进前台窗口，未到前台即中止
 *  · **最多尝试 1 次**；失败即写 login-guard.json 自锁（防连续失败锁账户）
 * 所以这里不提供任何"重试次数"参数，也不做循环。
 */
export const liveUnlock = (credFile?: string, timeout = 200) =>
  api.post<LiveRun>('/api/live/unlock', { cred_file: credFile, timeout })

/**
 * **会产生真实委托**的下单/撤单。
 *
 * 安全约定（与后端 live.py 的闸门一一对应，两处都不能放松）：
 *  - `confirm: true` 是硬要求，否则后端 400
 *  - `submit: true` 才会真的提交；不带就是**预演**（切面板→填单→校验→截图，不提交）
 *  - `yes: true` 才跳过工具的人工确认框（agent 模式）
 * 所以调用方至少要显式写出 confirm，submit 由 UI 上「预演 / 真下单」两个按钮决定。
 */
export interface LiveOrderBody {
  mode: 'buy' | 'sell' | 'buy-multi' | 'sell-multi' | 'cancel'
  code?: string
  price?: string | number
  qty?: string | number
  legs?: string
  cancel_scope?: 'all-buy' | 'all-sell'
  submit?: boolean
  yes?: boolean
  allow_st?: boolean
  bg?: boolean
  timeout?: number
}

export const liveOrderflow = (body: LiveOrderBody) =>
  api.post<LiveRun>('/api/live/orderflow', { confirm: true, bg: true, ...body } as unknown as Record<string, unknown>)
