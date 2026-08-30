// Typed API surface for the SPA.
import { api } from './client'
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
  kline: { exists: boolean; max: string | null; rows: number }
  stock_list_rows: number
  cache: { exists: boolean; max: string | null; rows: number }
  fundamental: { exists: boolean; max: string | null; rows: number }
  needs_init: boolean
  settings: { theme: string; font_size: number }
  ai_configured: boolean
}

// ---- system ----
export const getBootstrap = () => api.get<Bootstrap>('/api/system/bootstrap')
export const getHealth = () => api.get('/api/system/health')
export const getSettings = () => api.get<Record<string, unknown>>('/api/system/settings')
export const saveSettings = (body: Record<string, unknown>) => api.post<Record<string, unknown>>('/api/system/settings', body)
export const testLlm = (agent: Record<string, unknown>) => api.post('/api/system/settings/test-llm', agent)

// ---- overview ----
export const getOverview = () => api.get<OverviewData>('/api/overview')

// ---- market ----
export const getIndices = () => api.get<IndexQuote[]>('/api/market/indices')
export const getSectors = (type = 'industry') => api.get<Record<string, unknown>[]>('/api/market/sectors', { type })
export const getNorthFlow = (days = 30) => api.get<Record<string, unknown>[]>('/api/market/north-flow', { days })
export const getNews = (code: string, limit = 20) => api.get<Record<string, unknown>[]>('/api/market/news', { code, limit })
export const getQuote = (codes: string[]) => api.get<IndexQuote[]>('/api/market/quote', { codes: codes.join(',') })

// ---- kline / stock ----
export const getKline = (code: string, days = 250) => api.get<KlineBar[]>('/api/kline', { code, days })
export const getCyq = (code: string) => api.get<Record<string, unknown>[]>('/api/kline/cyq', { code })
export const searchStock = (q: string) => api.get<StockRef[]>('/api/stock/search', { q })

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
export const getPicks = (top = 20) => api.get<{ items: PickItem[]; total: number; stale: boolean; ts: number }>('/api/picks', { top })
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

// ---- agentops ----
export interface ScanResult { code: string; triggered: boolean; price: number }
export interface DeepEntry { code: string; name: string; verdict: string; reason: string; confidence: number; news: unknown[] }
export interface PortfolioSnapshot {
  account_id: number; name: string; cash: number; total_assets: number;
  holdings: Record<string, number>; prices: Record<string, number>; current_weights: Record<string, number>
}

export const scanEntry = (code: string, contract: Record<string, unknown>) => api.post<ScanResult>('/api/agentops/scan', { code, contract })
export const deepAnalyze = (candidates: string[]) => api.post<{ entries: DeepEntry[] }>('/api/agentops/deep', { candidates })
export const portfolioRebalance = (account_id: number) => api.post<PortfolioSnapshot>('/api/agentops/portfolio/rebalance', { account_id })
export const getAgentStrategies = () => api.get<StrategyDef[]>('/api/agentops/strategies')

// ---- pipeline ----
export interface PipelineStatus { last_update: string | null; status: string; steps?: Record<string, unknown> }
export interface PipelineStats { stock_count: number; kline_rows: number; latest_date: string | null; db_size: string }

export const triggerPipelineUpdate = (pool_only = false) => api.post<JobHandle>('/api/pipeline/update', { pool_only })
export const getPipelineStatus = () => api.get<PipelineStatus>('/api/pipeline/status')
export const getPipelineStats = () => api.get<PipelineStats>('/api/pipeline/stats')

// ---- trainer ----
export interface TrainerSnapshot {
  cursor: number; total_bars: number; progress: number; balance: number;
  floating_pnl: number; total_equity: number; realized_pnl: number; win_rate: number;
  open_orders: unknown[]; closed_orders: unknown[]; current_price: number; current_date: string
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
