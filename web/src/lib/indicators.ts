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

// ==================== 副图指标（注册表驱动） ====================

export type OhlcBar = { high: number; low: number; close: number; open?: number; volume?: number }

/** OBV 能量潮（收盘方向加权累计量）+ MAOBV(30) */
export function obv(bars: OhlcBar[], n = 30) {
  const out: IndSeries = []
  let acc = 0
  for (let i = 0; i < bars.length; i++) {
    const v = bars[i].volume ?? 0
    if (i === 0) acc = v
    else {
      const prev = bars[i - 1].close
      if (bars[i].close > prev) acc += v
      else if (bars[i].close < prev) acc -= v
    }
    out.push(acc)
  }
  return { obv: out, ma: sma(out.map((x) => x ?? 0), n) }
}

/** CCI 顺势指标 */
export function cci(bars: OhlcBar[], n = 14): IndSeries {
  const tp = bars.map((b) => (b.high + b.low + b.close) / 3)
  const out: IndSeries = new Array(bars.length).fill(null)
  for (let i = n - 1; i < bars.length; i++) {
    const win = tp.slice(i - n + 1, i + 1)
    const ma = win.reduce((a, x) => a + x, 0) / n
    const mad = win.reduce((a, x) => a + Math.abs(x - ma), 0) / n
    out[i] = mad > 0 ? (tp[i] - ma) / (0.015 * mad) : 0
  }
  return out
}

/** 威廉指标 WR（通达信口径：0~100，越大越超卖） */
export function wr(bars: OhlcBar[], n = 10): IndSeries {
  const out: IndSeries = new Array(bars.length).fill(null)
  for (let i = n - 1; i < bars.length; i++) {
    let hi = -Infinity
    let lo = Infinity
    for (let j = i - n + 1; j <= i; j++) {
      if (bars[j].high > hi) hi = bars[j].high
      if (bars[j].low < lo) lo = bars[j].low
    }
    out[i] = hi === lo ? 50 : ((hi - bars[i].close) / (hi - lo)) * 100
  }
  return out
}

/** DMI 趋向指标（Wilder 平滑）：+DI / -DI / ADX */
export function dmi(bars: OhlcBar[], n = 14) {
  const len = bars.length
  const pdi: IndSeries = new Array(len).fill(null)
  const mdi: IndSeries = new Array(len).fill(null)
  const adx: IndSeries = new Array(len).fill(null)
  if (len < n + 2) return { pdi, mdi, adx }
  let trS = 0
  let pS = 0
  let mS = 0
  const dxs: number[] = []
  for (let i = 1; i < len; i++) {
    const up = bars[i].high - bars[i - 1].high
    const dn = bars[i - 1].low - bars[i].low
    const pDM = up > dn && up > 0 ? up : 0
    const mDM = dn > up && dn > 0 ? dn : 0
    const tr = Math.max(bars[i].high - bars[i].low, Math.abs(bars[i].high - bars[i - 1].close), Math.abs(bars[i].low - bars[i - 1].close))
    if (i <= n) {
      trS += tr
      pS += pDM
      mS += mDM
      if (i === n) {
        pdi[i] = trS ? (pS / trS) * 100 : 0
        mdi[i] = trS ? (mS / trS) * 100 : 0
      }
    } else {
      trS = trS - trS / n + tr
      pS = pS - pS / n + pDM
      mS = mS - mS / n + mDM
      const p = trS ? (pS / trS) * 100 : 0
      const m = trS ? (mS / trS) * 100 : 0
      pdi[i] = p
      mdi[i] = m
    }
    if (i > n) {
      const sum = (pdi[i] ?? 0) + (mdi[i] ?? 0)
      dxs.push(sum ? (Math.abs((pdi[i] ?? 0) - (mdi[i] ?? 0)) / sum) * 100 : 0)
    }
  }
  // ADX = DX 的 n 日 Wilder 平滑
  let adxV: number | null = null
  let idx = 0
  const start = n * 2
  for (let i = 0; i < len; i++) {
    const need = i - start + 1
    if (need <= 0) continue
    if (adxV == null && need >= n) {
      adxV = dxs.slice(0, n).reduce((a, x) => a + x, 0) / n
      adx[i] = adxV
      idx = n
    } else if (adxV != null && idx < dxs.length) {
      adxV = (adxV * (n - 1) + dxs[idx]) / n
      adx[i] = adxV
      idx++
    }
  }
  return { pdi, mdi, adx }
}

/** BIAS 乖离率 */
export function bias(closes: number[], n: number): IndSeries {
  const ma = sma(closes, n)
  return closes.map((c, i) => (ma[i] != null && ma[i] !== 0 ? ((c - ma[i]!) / ma[i]!) * 100 : null))
}

/** ATR（Wilder 平滑） */
export function atrLine(bars: OhlcBar[], n = 14): IndSeries {
  const out: IndSeries = new Array(bars.length).fill(null)
  if (bars.length < n + 1) return out
  let v: number | null = null
  for (let i = 1; i < bars.length; i++) {
    const tr = Math.max(bars[i].high - bars[i].low, Math.abs(bars[i].high - bars[i - 1].close), Math.abs(bars[i].low - bars[i - 1].close))
    if (i <= n) {
      v = (v ?? 0) + tr / n
      if (i === n) out[i] = v
    } else {
      v = ((v ?? 0) * (n - 1) + tr) / n
      out[i] = v
    }
  }
  return out
}

/** PSY 心理线 + PSYMA */
export function psy(closes: number[], n = 12, mn = 6) {
  const out: IndSeries = new Array(closes.length).fill(null)
  let up = 0
  for (let i = 1; i < closes.length; i++) {
    up += closes[i] > closes[i - 1] ? 1 : 0
    if (i > n) up -= closes[i - n + 1] > closes[i - n] ? 1 : 0
    if (i >= n) out[i] = (up / n) * 100
  }
  return { psy: out, ma: sma(out.map((x) => x ?? 0), mn) }
}

/** VR 成交量比率（n=26） */
export function vrLine(bars: OhlcBar[], n = 26): IndSeries {
  const out: IndSeries = new Array(bars.length).fill(null)
  for (let i = n - 1; i < bars.length; i++) {
    let up = 0
    let dn = 0
    let flat = 0
    for (let j = i - n + 1; j <= i; j++) {
      const v = bars[j].volume ?? 0
      const c = bars[j].close
      const pc = j > 0 ? bars[j - 1].close : c
      if (c > pc) up += v
      else if (c < pc) dn += v
      else flat += v
    }
    const denom = dn + flat / 2
    out[i] = denom > 0 ? ((up + flat / 2) / denom) * 100 : 0
  }
  return out
}

// ---- 副图注册表：加指标只改这里 + SUB_SPECS ----
export interface SubSeriesDef { key: string; label: string; hist?: boolean }
export interface SubSpec { label: string; series: SubSeriesDef[] }

export const SUB_SPECS: Record<string, SubSpec> = {
  macd: { label: 'MACD', series: [{ key: 'hist', label: 'MACD', hist: true }, { key: 'dif', label: 'DIF' }, { key: 'dea', label: 'DEA' }] },
  kdj: { label: 'KDJ', series: [{ key: 'k', label: 'K' }, { key: 'd', label: 'D' }, { key: 'j', label: 'J' }] },
  rsi: { label: 'RSI', series: [{ key: 'rsi6', label: 'RSI6' }, { key: 'rsi12', label: 'RSI12' }, { key: 'rsi24', label: 'RSI24' }] },
  obv: { label: 'OBV', series: [{ key: 'obv', label: 'OBV' }, { key: 'ma', label: 'MAOBV' }] },
  cci: { label: 'CCI', series: [{ key: 'cci', label: 'CCI(14)' }] },
  wr: { label: 'WR', series: [{ key: 'wr10', label: 'WR10' }, { key: 'wr6', label: 'WR6' }] },
  dmi: { label: 'DMI', series: [{ key: 'pdi', label: '+DI' }, { key: 'mdi', label: '-DI' }, { key: 'adx', label: 'ADX' }] },
  bias: { label: 'BIAS', series: [{ key: 'b6', label: 'BIAS6' }, { key: 'b12', label: 'BIAS12' }, { key: 'b24', label: 'BIAS24' }] },
  atr: { label: 'ATR', series: [{ key: 'atr', label: 'ATR14' }] },
  psy: { label: 'PSY', series: [{ key: 'psy', label: 'PSY(12)' }, { key: 'ma', label: 'PSYMA' }] },
  vr: { label: 'VR', series: [{ key: 'vr', label: 'VR(26)' }] },
}

/** 按注册表计算副图数据（键与 SUB_SPECS[key].series[].key 对应） */
export function computeSub(kind: string, bars: OhlcBar[]): Record<string, IndSeries> | null {
  if (!SUB_SPECS[kind] || !bars.length) return null
  const closes = bars.map((b) => b.close)
  switch (kind) {
    case 'macd': { const { dif, dea, hist } = macd(closes); return { dif, dea, hist } }
    case 'kdj': { const { k, d, j } = kdj(bars, 9); return { k, d, j } }
    case 'rsi': return { rsi6: rsi(closes, 6), rsi12: rsi(closes, 12), rsi24: rsi(closes, 24) }
    case 'obv': { const { obv: o, ma } = obv(bars); return { obv: o, ma } }
    case 'cci': return { cci: cci(bars, 14) }
    case 'wr': return { wr10: wr(bars, 10), wr6: wr(bars, 6) }
    case 'dmi': { const { pdi, mdi, adx } = dmi(bars, 14); return { pdi, mdi, adx } }
    case 'bias': return { b6: bias(closes, 6), b12: bias(closes, 12), b24: bias(closes, 24) }
    case 'atr': return { atr: atrLine(bars, 14) }
    case 'psy': { const { psy: p, ma } = psy(closes, 12, 6); return { psy: p, ma } }
    case 'vr': return { vr: vrLine(bars, 26) }
    default: return null
  }
}
