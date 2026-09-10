// 选股依据（候选池快照）通用类型与展示助手。
// 后端来源：backend/trader/selection.py:build_snapshot → 随决策落库，事后可核对。
export interface CandGroup { id?: string; name: string; weight?: number; score: number }
export interface CandPick {
  rank: number; code: string; name: string; score: number
  groups?: CandGroup[]
}
export interface CandSnapshot {
  as_of?: string
  chain?: string
  universe?: string
  mode?: string
  scorecard?: {
    name?: string; version?: string; data_window?: number
    groups?: { id: string; name: string; weight: number; max_score?: number }[]
    error?: string
  }
  filters?: { rule: string; on: boolean }[]
  stats?: Record<string, number>
  picks?: CandPick[]
  events?: { code?: string; name?: string; reason?: string }[]
  hot_sectors?: string[]
  error?: string
}

export function filtersOn(c?: CandSnapshot): string[] {
  return (c?.filters || []).filter((f) => f.on).map((f) => f.rule)
}
export function filtersOff(c?: CandSnapshot): string[] {
  return (c?.filters || []).filter((f) => !f.on).map((f) => f.rule)
}
export function groupWeights(c?: CandSnapshot): string {
  return (c?.scorecard?.groups || []).map((g) => `${g.name} ${g.weight}`).join(' · ')
}
export function funnelText(c?: CandSnapshot): string[] {
  const s = c?.stats || {}
  const out: string[] = []
  if (s.universe_total != null) out.push(`股票池 ${s.universe_total} 只`)
  if (s.after_filters != null) out.push(`过滤后 ${s.after_filters} 只`)
  if (s.scored != null) out.push(`实际评分 ${s.scored} 只`)
  if (s.skipped_short_history) out.push(`K线不足跳过 ${s.skipped_short_history} 只`)
  if (s.failed) out.push(`取数失败 ${s.failed} 只`)
  return out
}
export function candCount(c?: CandSnapshot): number {
  return (c?.picks || []).length
}
// 旧决策没记录候选池时不要渲染空块
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function hasCands(c?: any): boolean {
  return !!(c && ((c.picks || []).length || (c.filters || []).length || c.as_of))
}
