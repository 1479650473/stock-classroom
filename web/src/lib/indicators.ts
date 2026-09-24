/**
 * 前端技术指标计算（口径与后端 backend/indicators.py 一致：MACD 柱 ×2、KDJ 3 日平滑、RSI Wilder）。
 * 输入均为「按时间升序」的数组，输出等长数组，未定义位置为 null。
 */

export type IndSeries = (number | null)[]

export interface BarLike {
  high: number
  low: number
  close: number
}

/** 简单移动平均 */
export function sma(vals: number[], n: number): IndSeries {
  const out: IndSeries = new Array(vals.length).fill(null)
  if (n <= 0) return out
  let sum = 0
  for (let i = 0; i < vals.length; i++) {
    sum += vals[i]
    if (i >= n) sum -= vals[i - n]
    if (i >= n - 1) out[i] = sum / n
  }
  return out
}

/** 指数移动平均（首值起步） */
export function ema(vals: number[], n: number): IndSeries {
  const out: IndSeries = new Array(vals.length).fill(null)
  if (!vals.length || n <= 0) return out
  const k = 2 / (n + 1)
  let prev = vals[0]
  out[0] = prev
  for (let i = 1; i < vals.length; i++) {
    prev = vals[i] * k + prev * (1 - k)
    out[i] = prev
  }
  return out
}

/** MACD（dif/dea/hist，hist = 2×(dif-dea) 国内软件口径） */
export function macd(closes: number[], fast = 12, slow = 26, signal = 9) {
  const ef = ema(closes, fast)
  const es = ema(closes, slow)
  const dif: IndSeries = closes.map((_, i) =>
    ef[i] != null && es[i] != null ? ef[i]! - es[i]! : null,
  )
  const deaRaw = ema(dif.map((v) => v ?? 0), signal)
  const dea: IndSeries = dif.map((v, i) => (v == null ? null : deaRaw[i]))
  const hist: IndSeries = dif.map((v, i) => (v != null && dea[i] != null ? (v - dea[i]!) * 2 : null))
  return { dif, dea, hist }
}

/** KDJ（N=9，K/D 初值 50，K=2/3K+1/3RSV） */
export function kdj(bars: BarLike[], n = 9) {
  const K: IndSeries = []
  const D: IndSeries = []
  const J: IndSeries = []
  let k = 50
  let d = 50
  for (let i = 0; i < bars.length; i++) {
    const from = Math.max(0, i - n + 1)
    let hi = -Infinity
    let lo = Infinity
    for (let j = from; j <= i; j++) {
      if (bars[j].high > hi) hi = bars[j].high
      if (bars[j].low < lo) lo = bars[j].low
    }
    const close = bars[i].close
    const rsv = hi === lo ? 50 : ((close - lo) / (hi - lo)) * 100
    k = (2 / 3) * k + (1 / 3) * rsv
    d = (2 / 3) * d + (1 / 3) * k
    K.push(i >= n - 1 ? k : null)
    D.push(i >= n - 1 ? d : null)
    J.push(i >= n - 1 ? 3 * k - 2 * d : null)
  }
  return { k: K, d: D, j: J }
}

/** RSI（Wilder 平滑） */
export function rsi(closes: number[], n = 14): IndSeries {
  const out: IndSeries = new Array(closes.length).fill(null)
  if (closes.length <= n) return out
  let up = 0
  let dn = 0
  for (let i = 1; i <= n; i++) {
    const ch = closes[i] - closes[i - 1]
    up += Math.max(ch, 0)
    dn += Math.max(-ch, 0)
  }
  up /= n
  dn /= n
  const val = () => (dn === 0 ? 100 : 100 - 100 / (1 + up / dn))
  out[n] = val()
  for (let i = n + 1; i < closes.length; i++) {
    const ch = closes[i] - closes[i - 1]
    up = (up * (n - 1) + Math.max(ch, 0)) / n
    dn = (dn * (n - 1) + Math.max(-ch, 0)) / n
    out[i] = val()
  }
  return out
}

/** 布林带（N=20, K=2） */
export function boll(closes: number[], n = 20, k = 2) {
  const mid = sma(closes, n)
  const upper: IndSeries = new Array(closes.length).fill(null)
  const lower: IndSeries = new Array(closes.length).fill(null)
  for (let i = n - 1; i < closes.length; i++) {
    const m = mid[i]
    if (m == null) continue
    let s = 0
    for (let j = i - n + 1; j <= i; j++) s += (closes[j] - m) ** 2
    const sd = Math.sqrt(s / n)
    upper[i] = m + k * sd
    lower[i] = m - k * sd
  }
  return { mid, upper, lower }
}

/** 分时均价线：累计成交额 / 累计成交量（金额单位元、量单位股 → 元/股） */
export function timeshareAvg(bars: { volume?: number; amount?: number; close: number }[]): number[] {
  const out: number[] = []
  let cumAmt = 0
  let cumVol = 0
  for (const b of bars) {
    cumAmt += b.amount ?? 0
    cumVol += b.volume ?? 0
    out.push(cumVol > 0 && cumAmt > 0 ? cumAmt / cumVol : b.close)
  }
  return out
}
