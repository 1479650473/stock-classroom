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
export function kdj(bars: BarLike[], n = 9, m1 = 3, m2 = 3) {
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
    // 通达信 KDJ：K=(m1-1)/m1·K + 1/m1·RSV；D 同（默认 m1=m2=3）
    k = ((m1 - 1) / m1) * k + (1 / m1) * rsv
    d = ((m2 - 1) / m2) * d + (1 / m2) * k
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


// ---- 追加指标（第二批） ----

/** TRIX 三重指数平滑（12,9，通达信口径 ×100） */
export function trixLine(closes: number[], n = 12, m = 9) {
  const e1 = ema(closes, n).map((x) => x ?? 0)
  const e2 = ema(e1, n).map((x) => x ?? 0)
  const e3 = ema(e2, n).map((x) => x ?? 0)
  const trix: IndSeries = new Array(closes.length).fill(null)
  for (let i = 1; i < closes.length; i++) {
    if (i < n * 3) continue
    const prev = e3[i - 1]
    trix[i] = prev ? ((e3[i] - prev) / prev) * 100 : 0
  }
  return { trix, ma: sma(trix.map((x) => x ?? 0), m) }
}

/** MTM 动量（12）+ MTMMA(6) */
export function mtm(closes: number[], n = 12, m = 6) {
  const out: IndSeries = new Array(closes.length).fill(null)
  for (let i = n; i < closes.length; i++) out[i] = closes[i] - closes[i - n]
  return { mtm: out, ma: sma(out.map((x) => x ?? 0), m) }
}

/** ARBR 人气意愿（26）：AR = 上行力度/下行力度，BR = 昨收比较 */
export function arbr(bars: OhlcBar[], n = 26) {
  const ar: IndSeries = new Array(bars.length).fill(null)
  const br: IndSeries = new Array(bars.length).fill(null)
  for (let i = n - 1; i < bars.length; i++) {
    let upAR = 0
    let dnAR = 0
    let upBR = 0
    let dnBR = 0
    for (let j = i - n + 1; j <= i; j++) {
      const b = bars[j]
      const pc = j > 0 ? bars[j - 1].close : b.close
      upAR += b.high - (b.open ?? b.close)
      dnAR += (b.open ?? b.close) - b.low
      upBR += Math.max(0, b.high - pc)
      dnBR += Math.max(0, pc - b.low)
    }
    ar[i] = dnAR > 0 ? (upAR / dnAR) * 100 : 0
    br[i] = dnBR > 0 ? (upBR / dnBR) * 100 : 0
  }
  return { ar, br }
}

/** ROC 变动率（12）+ MAROC(6) */
export function roc(closes: number[], n = 12, m = 6) {
  const out: IndSeries = new Array(closes.length).fill(null)
  for (let i = n; i < closes.length; i++) {
    const p = closes[i - n]
    out[i] = p ? ((closes[i] - p) / p) * 100 : 0
  }
  return { roc: out, ma: sma(out.map((x) => x ?? 0), m) }
}

/** SAR 抛物线转向：返回 { up, down } 两条错位序列（多/空各自成段） */
export function sar(bars: OhlcBar[], af0 = 0.02, step = 0.02, maxAf = 0.2) {
  const up: IndSeries = new Array(bars.length).fill(null)
  const down: IndSeries = new Array(bars.length).fill(null)
  if (bars.length < 2) return { up, down }
  let isUp = true
  let af = af0
  let ep = bars[0].high
  let v = bars[0].low
  for (let i = 1; i < bars.length; i++) {
    v = v + af * (ep - v)
    if (isUp) {
      if (bars[i].low < v) {
        isUp = false
        v = ep
        ep = bars[i].low
        af = af0
      } else if (bars[i].high > ep) {
        ep = bars[i].high
        af = Math.min(af + step, maxAf)
      }
    } else {
      if (bars[i].high > v) {
        isUp = true
        v = ep
        ep = bars[i].high
        af = af0
      } else if (bars[i].low < ep) {
        ep = bars[i].low
        af = Math.min(af + step, maxAf)
      }
    }
    if (isUp) up[i] = v
    else down[i] = v
  }
  return { up, down }
}

// ---- 副图注册表：加指标只改这里 + SUB_SPECS ----
export interface SubSeriesDef { key: string; label: string; hist?: boolean }
export interface SubParamDef { key: string; label: string; def: number; min?: number; max?: number }
export interface SubSpec { label: string; series: SubSeriesDef[]; params: SubParamDef[] }
export type SubParams = Record<string, number>

export const SUB_SPECS: Record<string, SubSpec> = {
  macd: { label: 'MACD', params: [{ key: 'fast', label: '快', def: 12 }, { key: 'slow', label: '慢', def: 26 }, { key: 'signal', label: '信号', def: 9 }],
    series: [{ key: 'hist', label: 'MACD', hist: true }, { key: 'dif', label: 'DIF' }, { key: 'dea', label: 'DEA' }] },
  kdj: { label: 'KDJ', params: [{ key: 'n', label: 'N', def: 9 }, { key: 'm1', label: 'M1', def: 3 }, { key: 'm2', label: 'M2', def: 3 }],
    series: [{ key: 'k', label: 'K' }, { key: 'd', label: 'D' }, { key: 'j', label: 'J' }] },
  rsi: { label: 'RSI', params: [{ key: 'n1', label: 'N1', def: 6 }, { key: 'n2', label: 'N2', def: 12 }, { key: 'n3', label: 'N3', def: 24 }],
    series: [{ key: 'rsi1', label: 'RSI1' }, { key: 'rsi2', label: 'RSI2' }, { key: 'rsi3', label: 'RSI3' }] },
  obv: { label: 'OBV', params: [{ key: 'ma', label: '均线', def: 30 }],
    series: [{ key: 'obv', label: 'OBV' }, { key: 'ma', label: 'MAOBV' }] },
  cci: { label: 'CCI', params: [{ key: 'n', label: 'N', def: 14 }], series: [{ key: 'cci', label: 'CCI' }] },
  wr: { label: 'WR', params: [{ key: 'n1', label: 'N1', def: 10 }, { key: 'n2', label: 'N2', def: 6 }],
    series: [{ key: 'wr1', label: 'WR1' }, { key: 'wr2', label: 'WR2' }] },
  dmi: { label: 'DMI', params: [{ key: 'n', label: 'N', def: 14 }],
    series: [{ key: 'pdi', label: '+DI' }, { key: 'mdi', label: '-DI' }, { key: 'adx', label: 'ADX' }] },
  bias: { label: 'BIAS', params: [{ key: 'n1', label: 'N1', def: 6 }, { key: 'n2', label: 'N2', def: 12 }, { key: 'n3', label: 'N3', def: 24 }],
    series: [{ key: 'b1', label: 'BIAS1' }, { key: 'b2', label: 'BIAS2' }, { key: 'b3', label: 'BIAS3' }] },
  atr: { label: 'ATR', params: [{ key: 'n', label: 'N', def: 14 }], series: [{ key: 'atr', label: 'ATR' }] },
  psy: { label: 'PSY', params: [{ key: 'n', label: 'N', def: 12 }, { key: 'm', label: '均线', def: 6 }],
    series: [{ key: 'psy', label: 'PSY' }, { key: 'ma', label: 'PSYMA' }] },
  vr: { label: 'VR', params: [{ key: 'n', label: 'N', def: 26 }], series: [{ key: 'vr', label: 'VR' }] },
  trix: { label: 'TRIX', params: [{ key: 'n', label: 'N', def: 12 }, { key: 'm', label: '均线', def: 9 }],
    series: [{ key: 'trix', label: 'TRIX' }, { key: 'ma', label: 'MATRIX' }] },
  mtm: { label: 'MTM', params: [{ key: 'n', label: 'N', def: 12 }, { key: 'm', label: '均线', def: 6 }],
    series: [{ key: 'mtm', label: 'MTM' }, { key: 'ma', label: 'MTMMA' }] },
  arbr: { label: 'ARBR', params: [{ key: 'n', label: 'N', def: 26 }],
    series: [{ key: 'ar', label: 'AR' }, { key: 'br', label: 'BR' }] },
  roc: { label: 'ROC', params: [{ key: 'n', label: 'N', def: 12 }, { key: 'm', label: '均线', def: 6 }],
    series: [{ key: 'roc', label: 'ROC' }, { key: 'ma', label: 'MAROC' }] },
}

/** 按注册表计算副图数据（键与 SUB_SPECS[key].series[].key 对应） */
/** 参数合并（缺省用注册表默认值；非法值回退默认） */
export function resolveParams(kind: string, params?: SubParams): SubParams {
  const out: SubParams = {}
  const spec = SUB_SPECS[kind]
  if (!spec) return out
  for (const p of spec.params) {
    const v = params ? Number(params[p.key]) : NaN
    out[p.key] = Number.isFinite(v) && v > 0 ? Math.round(v) : p.def
  }
  return out
}

/** 按注册表计算副图数据（键与 SPEC.series[].key 对应；params 缺省=默认参数） */
export function computeSub(kind: string, bars: OhlcBar[], params?: SubParams): Record<string, IndSeries> | null {
  if (!SUB_SPECS[kind] || !bars.length) return null
  const closes = bars.map((b) => b.close)
  const P = resolveParams(kind, params)
  switch (kind) {
    case 'macd': { const { dif, dea, hist } = macd(closes, P.fast, P.slow, P.signal); return { dif, dea, hist } }
    case 'kdj': { const { k, d, j } = kdj(bars, P.n, P.m1, P.m2); return { k, d, j } }
    case 'rsi': return { rsi1: rsi(closes, P.n1), rsi2: rsi(closes, P.n2), rsi3: rsi(closes, P.n3) }
    case 'obv': { const { obv: o, ma } = obv(bars, P.ma); return { obv: o, ma } }
    case 'cci': return { cci: cci(bars, P.n) }
    case 'wr': return { wr1: wr(bars, P.n1), wr2: wr(bars, P.n2) }
    case 'dmi': { const { pdi, mdi, adx } = dmi(bars, P.n); return { pdi, mdi, adx } }
    case 'bias': return { b1: bias(closes, P.n1), b2: bias(closes, P.n2), b3: bias(closes, P.n3) }
    case 'atr': return { atr: atrLine(bars, P.n) }
    case 'psy': { const { psy: p, ma } = psy(closes, P.n, P.m); return { psy: p, ma } }
    case 'vr': return { vr: vrLine(bars, P.n) }
    case 'trix': { const { trix, ma } = trixLine(closes, P.n, P.m); return { trix, ma } }
    case 'mtm': { const { mtm: m2, ma } = mtm(closes, P.n, P.m); return { mtm: m2, ma } }
    case 'arbr': { const { ar, br } = arbr(bars, P.n); return { ar, br } }
    case 'roc': { const { roc: r2, ma } = roc(closes, P.n, P.m); return { roc: r2, ma } }
    default: return null
  }
}
