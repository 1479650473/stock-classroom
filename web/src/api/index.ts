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
export const getPaperPortfolio = () =>
  api.get<PaperPortfolio>('/api/alpha/paper', {}, { ttl: 60_000 })

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
