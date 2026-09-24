<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import {
  createChart, CandlestickSeries, HistogramSeries, LineSeries, AreaSeries, LineStyle, CrosshairMode,
  createSeriesMarkers,
} from 'lightweight-charts'
import type {
  IChartApi, ISeriesApi, Time, SeriesMarker, IPriceLine, ISeriesMarkersPluginApi, MouseEventParams,
} from 'lightweight-charts'
import Icon from '@/components/Icon.vue'
import { cssVar } from '@/composables/useEChart'
import { chartTokens, maColors, withAlpha } from '@/lib/chartTheme'
import {
  boll as calcBoll, kdj as calcKdj, macd as calcMacd, rsi as calcRsi, timeshareAvg,
} from '@/lib/indicators'

/**
 * 专业 K 线：TradingView Lightweight Charts v5 封装。
 * 支持：蜡烛/分时、均线多组、布林带、量、资金流、权益、买卖标记、涨跌停标记、
 *       十字光标信息条、副图指标（MACD/KDJ/RSI）、缩放/复位/截图/全屏。
 */
export interface LwcBar {
  time: string | number
  open: number
  high: number
  low: number
  close: number
  volume?: number
  amount?: number
}

export interface LwcMarker {
  time: string
  position: 'aboveBar' | 'belowBar' | 'inBar'
  color: string
  shape: 'circle' | 'square' | 'arrowUp' | 'arrowDown'
  text?: string
}

export interface LwcSpan {
  from: string
  to: string
  color?: string
}

/** 资金流副图数据(主力净流入, 与 K线时间对齐) */
export interface LwcFundFlow {
  time: string
  mainNet: number
  mainRatio?: number
}

interface LegendCell { label: string; value: string; color?: string }

const props = withDefaults(
  defineProps<{
    bars: LwcBar[]
    /** 均线周期（可运行时增删） */
    mas?: number[]
    /** 买卖点标记 */
    markers?: LwcMarker[]
    /** 播放头所在时间（竖线） */
    playheadTime?: string | null
    playheadColor?: string
    /** 持仓区间高亮 */
    spans?: LwcSpan[]
    showVolume?: boolean
    height?: number
    /** 权益曲线（独立 pane；showEquity 决定窗格是否预留，数据可后到） */
    equity?: { time: string; value: number }[]
    /** 是否预留权益窗格 */
    showEquity?: boolean
    /** 资金流副图（主力净流入柱状, 独立 pane；showFundFlow 决定窗格是否预留） */
    fundFlow?: LwcFundFlow[]
    /** 是否预留资金流窗格 */
    showFundFlow?: boolean
    /** 涨跌停判定阈值（0.098 主板 / 0.198 创业科创 / 0.048 ST）；0 = 不标记 */
    limitPct?: number
    /** 成交量均线周期（0 = 不画） */
    volumeMa?: number
    /** 分钟级数据：时间轴显示「时:分」 */
    intraday?: boolean
    /** 分时模式：价格线 + 均价线 + 昨收基准虚线 */
    timeshare?: boolean
    /** 分时基准价（昨收） */
    prevClose?: number | null
    /** 副图指标（第二指标窗） */
    sub?: 'none' | 'macd' | 'kdj' | 'rsi'
    /** 主图布林带 */
    boll?: boolean
    /** 右上角工具（缩放/复位/截图/全屏） */
    showTools?: boolean
    /** 左上角十字光标信息条 */
    showLegend?: boolean
    /** 截图文件名前缀 */
    title?: string
  }>(),
  {
    mas: () => [5, 20],
    markers: () => [],
    playheadTime: null,
    playheadColor: '#D4A574',
    spans: () => [],
    showVolume: true,
    height: 420,
    equity: () => [],
    showEquity: false,
    fundFlow: () => [],
    showFundFlow: false,
    limitPct: 0,
    volumeMa: 5,
    intraday: false,
    timeshare: false,
    prevClose: null,
    sub: 'none',
    boll: false,
    showTools: true,
    showLegend: true,
    title: '',
  },
)

const emit = defineEmits<{ periodKey: [index: number] }>()

const wrapEl = ref<HTMLDivElement>()
const el = ref<HTMLDivElement>()
const playheadEl = ref<HTMLDivElement>()
const chart = shallowRef<IChartApi | null>(null)
const candleSeries = shallowRef<ISeriesApi<'Candlestick'> | null>(null)
const volumeSeries = shallowRef<ISeriesApi<'Histogram'> | null>(null)
const equitySeries = shallowRef<ISeriesApi<'Area'> | null>(null)
const fundFlowSeries = shallowRef<ISeriesApi<'Histogram'> | null>(null)
const volMaSeries = shallowRef<ISeriesApi<'Line'> | null>(null)
const tsPriceSeries = shallowRef<ISeriesApi<'Area'> | null>(null)
const tsAvgSeries = shallowRef<ISeriesApi<'Line'> | null>(null)
const bollSeries = shallowRef<ISeriesApi<'Line'>[]>([])
let maSeries: ISeriesApi<'Line'>[] = []
let subSeries: ISeriesApi<'Line' | 'Histogram'>[] = []
let priceLine: IPriceLine | null = null
let prevLine: IPriceLine | null = null
let markersPlugin: ISeriesMarkersPluginApi<Time> | null = null
let ro: ResizeObserver | null = null
let mo: MutationObserver | null = null
let rafId = 0
let idxByTime = new Map<string, number>()

const legendRows = ref<LegendCell[][]>([])
const paneCount = ref(0)
const isFs = ref(false)
const rangeTick = ref(0)

// ---- 区间测量 ----
interface SelStats { n: number; from: string; to: string; chg: number; hi: number; lo: number; amp: number; vol: number; amt: number }
const measureOn = ref(false)
const sel = ref<{ i1: number; i2: number; stats: SelStats } | null>(null)
let dragging = false

function fmtT(t: string | number): string {
  const s = String(t)
  if (/^\d{9,10}$/.test(s)) {
    const d = new Date(Number(s) * 1000)
    return d.toISOString().slice(0, 16).replace('T', ' ')
  }
  return s
}

function computeSel(i1: number, i2: number): SelStats | null {
  const bars = props.bars
  if (!bars.length) return null
  const a = Math.max(0, Math.min(i1, i2))
  const b = Math.min(bars.length - 1, Math.max(i1, i2))
  const first = bars[a]
  const last = bars[b]
  let hi = -Infinity
  let lo = Infinity
  let vol = 0
  let amt = 0
  for (let k = a; k <= b; k++) {
    if (bars[k].high > hi) hi = bars[k].high
    if (bars[k].low < lo) lo = bars[k].low
    vol += bars[k].volume ?? 0
    amt += bars[k].amount ?? 0
  }
  const base = first.close || 1
  return {
    n: b - a + 1, from: fmtT(first.time), to: fmtT(last.time),
    chg: (last.close / base - 1) * 100,
    hi, lo, amp: ((hi - lo) / base) * 100, vol, amt,
  }
}

const selRect = computed(() => {
  const s = sel.value
  const ch = chart.value
  if (!s || !ch) return null
  void rangeTick.value
  const bars = props.bars
  const x1 = ch.timeScale().timeToCoordinate(bars[s.i1]?.time as Time)
  const x2 = ch.timeScale().timeToCoordinate(bars[s.i2]?.time as Time)
  if (x1 == null || x2 == null) return null
  return { left: Math.min(x1, x2), width: Math.max(2, Math.abs(x2 - x1)) }
})

function barIndexFromX(x: number): number {
  const ts = chart.value?.timeScale()
  if (!ts || !props.bars.length) return -1
  const lg = ts.coordinateToLogical(x)
  if (lg == null) return -1
  return Math.max(0, Math.min(props.bars.length - 1, Math.round(lg)))
}

function onWrapPointerDown(e: PointerEvent) {
  wrapEl.value?.focus({ preventScroll: true })
  if (!measureOn.value || !el.value) return
  const rect = el.value.getBoundingClientRect()
  const i = barIndexFromX(e.clientX - rect.left)
  if (i < 0) return
  dragging = true
  const stats = computeSel(i, i)
  if (stats) sel.value = { i1: i, i2: i, stats }
  window.addEventListener('pointermove', onWinMove)
  window.addEventListener('pointerup', onWinUp)
  e.preventDefault()
}

function onWinMove(ev: PointerEvent) {
  if (!dragging || !el.value || !sel.value) return
  const rect = el.value.getBoundingClientRect()
  const i = barIndexFromX(ev.clientX - rect.left)
  if (i < 0) return
  const stats = computeSel(sel.value.i1, i)
  if (stats) sel.value = { i1: sel.value.i1, i2: i, stats }
}

function onWinUp() {
  dragging = false
  window.removeEventListener('pointermove', onWinMove)
  window.removeEventListener('pointerup', onWinUp)
}

function toggleMeasure() {
  measureOn.value = !measureOn.value
  sel.value = null
  chart.value?.applyOptions({
    handleScroll: !measureOn.value,
    handleScale: !measureOn.value,
  })
  if (measureOn.value) wrapEl.value?.focus({ preventScroll: true })
}

function onKey(e: KeyboardEvent) {
  const t = e.target as HTMLElement | null
  if (t && /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName)) return
  const ts = chart.value?.timeScale()
  if (!ts) return
  if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
    const r = ts.getVisibleLogicalRange()
    if (!r) return
    const w = r.to - r.from
    const d = (e.key === 'ArrowLeft' ? -1 : 1) * Math.max(1, w * 0.12)
    ts.setVisibleLogicalRange({ from: r.from + d, to: r.to + d })
    e.preventDefault()
  } else if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
    zoom(e.key === 'ArrowUp' ? 0.8 : 1.25)
    e.preventDefault()
  } else if (e.key === 'Home') {
    resetView()
    e.preventDefault()
  } else if (e.key === 'Escape') {
    if (measureOn.value) toggleMeasure()
  } else if (/^[1-9]$/.test(e.key)) {
    emit('periodKey', Number(e.key) - 1)
    e.preventDefault()
  }
}

const MA_EXTRA = () => [tokens().up, tokens().info]

function tokens() { return chartTokens() }
function textColor() { return tokens().textSub }
function gridColor() { return tokens().borderSoft }
function borderColor() { return tokens().border }
function upColor() { return tokens().up }
function downColor() { return tokens().down }
function maColor(i: number) {
  const base = [...maColors(), ...MA_EXTRA()]
  return base[i % base.length]
}
function subPaneIndex(): number {
  // 主图 0 / 量 1 / 权益或资金流 2 / 指标窗（追加到末尾）
  const panes = chart.value ? chart.value.panes().length : 2
  const want = (props.showEquity || props.showFundFlow || props.equity.length || props.fundFlow.length) ? 3 : 2
  return Math.max(2, Math.min(want, panes))
}

function init() {
  if (!el.value) return
  chart.value = createChart(el.value, {
    width: el.value.clientWidth,
    height: props.height,
    layout: {
      background: { color: 'transparent' },
      textColor: textColor(),
      fontSize: 11,
      attributionLogo: false,
    },
    grid: {
      vertLines: { color: gridColor() },
      horzLines: { color: gridColor() },
    },
    crosshair: {
      mode: CrosshairMode.Normal,
      vertLine: { color: tokens().gold, width: 1, style: LineStyle.Dashed, labelBackgroundColor: tokens().panel },
      horzLine: { color: tokens().gold, width: 1, style: LineStyle.Dashed, labelBackgroundColor: tokens().panel },
    },
    rightPriceScale: { borderColor: borderColor() },
    timeScale: { borderColor: borderColor(), timeVisible: props.intraday, rightOffset: 2 },
  })

  candleSeries.value = chart.value.addSeries(CandlestickSeries, {
    upColor: upColor(),
    downColor: downColor(),
    borderUpColor: upColor(),
    borderDownColor: downColor(),
    wickUpColor: upColor(),
    wickDownColor: downColor(),
    visible: !props.timeshare,
  })

  // 分时（价格线 + 均价线）
  const line = cssVar('--accent', '#7AA2F7')
  tsPriceSeries.value = chart.value.addSeries(AreaSeries, {
    lineColor: line,
    lineWidth: 2,
    topColor: withAlpha(line, 0.22),
    bottomColor: withAlpha(line, 0.02),
    priceLineVisible: false,
    lastValueVisible: true,
    crosshairMarkerVisible: true,
    visible: props.timeshare,
  })
  tsAvgSeries.value = chart.value.addSeries(LineSeries, {
    color: tokens().gold,
    lineWidth: 1,
    priceLineVisible: false,
    lastValueVisible: false,
    crosshairMarkerVisible: false,
    visible: props.timeshare,
  })

  props.mas.forEach((_, i) => {
    const s = chart.value!.addSeries(LineSeries, {
      color: maColor(i),
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    })
    maSeries.push(s)
  })

  // 布林带（默认隐藏，props.boll 打开）
  bollSeries.value = [0, 1, 2].map((k) =>
    chart.value!.addSeries(LineSeries, {
      color: k === 1 ? tokens().textSub : withAlpha(tokens().textSub, 0.66),
      lineWidth: 1,
      lineStyle: k === 1 ? LineStyle.Solid : LineStyle.Solid,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
      visible: props.boll,
    }),
  )

  if (props.showVolume) {
    volumeSeries.value = chart.value.addSeries(
      HistogramSeries,
      { priceFormat: { type: 'volume' }, priceLineVisible: false, lastValueVisible: false },
      1,
    )
    if (props.volumeMa > 1) {
      volMaSeries.value = chart.value.addSeries(
        LineSeries,
        {
          color: tokens().textSub,
          lineWidth: 1,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
        },
        1,
      )
    }
  }

  if (props.showEquity || props.equity.length) {
    equitySeries.value = chart.value.addSeries(
      AreaSeries,
      {
        lineColor: line,
        lineWidth: 2,
        topColor: withAlpha(line, 0.28),
        bottomColor: withAlpha(line, 0.02),
        priceLineVisible: false,
        lastValueVisible: false,
      },
      2,
    )
  }

  if (props.showFundFlow || props.fundFlow.length) {
    fundFlowSeries.value = chart.value.addSeries(
      HistogramSeries,
      { priceFormat: { type: 'volume' }, priceLineVisible: false, lastValueVisible: false },
      2,
    )
  }

  if (props.sub !== 'none') ensureSub()

  ro = new ResizeObserver(() => {
    if (chart.value && el.value) {
      chart.value.applyOptions({ width: el.value.clientWidth, height: el.value.clientHeight || props.height })
      layoutPanes()
      schedulePlayhead()
    }
  })
  ro.observe(el.value)

  mo = new MutationObserver(() => applyTheme())
  mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })

  chart.value.timeScale().subscribeVisibleTimeRangeChange(schedulePlayhead)
  chart.value.subscribeCrosshairMove(onCrosshair)

  document.addEventListener('fullscreenchange', onFsChange)
  apply()
  layoutPanes()
}

/** 主图 / 量 / 指标窗高度比例（券商风格：主图占大头） */
function layoutPanes() {
  if (!chart.value) return
  try {
    const panes = chart.value.panes()
    const n = panes.length
    paneCount.value = n
    const sub = n >= 3
    panes[0]?.setStretchFactor(sub ? 6 : 4)
    panes[1]?.setStretchFactor(1.2)
    if (n >= 3) panes[2]?.setStretchFactor(1)
    if (n >= 4) panes[3]?.setStretchFactor(1.6)
  } catch {
    /* 不同版本 pane API 差异，失败不影响图表 */
  }
}

// ---- 副图指标 ----

/** 查找序列所在窗格 */
function paneIndexOf(s: unknown): number {
  const ch = chart.value
  if (!ch || !s) return -1
  const panes = ch.panes()
  for (let i = 0; i < panes.length; i++) {
    if (panes[i].getSeries().includes(s as never)) return i
  }
  return -1
}

function removePaneIfEmpty(idx: number) {
  const ch = chart.value
  if (!ch || idx < 0) return
  const panes = ch.panes()
  if (idx < panes.length && panes[idx].getSeries().length === 0) {
    try { ch.removePane(idx) } catch { /* 版本差异忽略 */ }
  }
}

/**
 * 结构同步：资金流/权益窗格按 show 标记增删，并保证窗格顺序 = 主图 / 量 / 资金流 / 指标。
 * （原来只在 init 时按当时数据建窗格 → 日K 切到分钟会留下空的资金流窗格）
 */
function syncStructure() {
  const ch = chart.value
  if (!ch) return
  const wantFlow = props.showFundFlow || props.fundFlow.length > 0
    || props.showEquity || props.equity.length > 0
  const flow = fundFlowSeries.value ?? equitySeries.value
  if (wantFlow && !flow) {
    // 建流量窗格（资金流优先，其次权益），再把它移到指标窗之前
    const line = cssVar('--accent', '#7AA2F7')
    if (props.showFundFlow || props.fundFlow.length > 0) {
      fundFlowSeries.value = ch.addSeries(
        HistogramSeries,
        { priceFormat: { type: 'volume' }, priceLineVisible: false, lastValueVisible: false },
        ch.panes().length,
      )
    } else {
      equitySeries.value = ch.addSeries(
        AreaSeries,
        {
          lineColor: line, lineWidth: 2,
          topColor: withAlpha(line, 0.28), bottomColor: withAlpha(line, 0.02),
          priceLineVisible: false, lastValueVisible: false,
        },
        ch.panes().length,
      )
    }
    const newIdx = ch.panes().length - 1
    const subIdx = paneIndexOf(subSeries[0])
    if (subIdx >= 0 && subIdx < newIdx) {
      try { ch.swapPanes(subIdx, newIdx) } catch { /* ignore */ }
    }
    apply()
  } else if (!wantFlow && flow) {
    const idx = paneIndexOf(flow)
    ch.removeSeries(flow)
    fundFlowSeries.value = null
    equitySeries.value = null
    removePaneIfEmpty(idx)
    layoutPanes()
  }
}

let subPaneOn = false
function ensureSub() {
  if (!chart.value) return
  subSeries.forEach((s) => chart.value!.removeSeries(s))
  subSeries = []
  if (props.sub === 'none') {
    // 关掉指标窗：移除空 pane（否则底部会留一块空白）
    if (subPaneOn) {
      try { chart.value.removePane(chart.value.panes().length - 1) } catch { /* 版本差异，忽略 */ }
      subPaneOn = false
    }
    layoutPanes()
    buildLegend(null)
    return
  }
  const pane = subPaneOn ? Math.max(1, chart.value.panes().length - 1) : subPaneIndex()
  const mkLine = (color: string, width = 1) => chart.value!.addSeries(LineSeries, {
    color, lineWidth: width as 1 | 2, priceLineVisible: false, lastValueVisible: false,
    crosshairMarkerVisible: false, priceFormat: { type: 'price', precision: 2, minMove: 0.01 },
  }, pane)
  if (props.sub === 'macd') {
    subSeries.push(chart.value.addSeries(HistogramSeries, {
      priceLineVisible: false, lastValueVisible: false, priceFormat: { type: 'price', precision: 2, minMove: 0.01 },
    }, pane))
    subSeries.push(mkLine(maColors()[0]!, 1))
    subSeries.push(mkLine(maColors()[1]!, 1))
  } else if (props.sub === 'kdj') {
    subSeries.push(mkLine(maColors()[0]!, 1))
    subSeries.push(mkLine(maColors()[1]!, 1))
    subSeries.push(mkLine(maColors()[2]!, 1))
  } else if (props.sub === 'rsi') {
    subSeries.push(mkLine(maColors()[0]!, 1))
    subSeries.push(mkLine(maColors()[1]!, 1))
    subSeries.push(mkLine(maColors()[2]!, 1))
  }
  subPaneOn = true
  layoutPanes()
  applySub()
}

function applySub() {
  if (!chart.value) return
  const bars = props.bars
  if (!bars.length || !subSeries.length) return
  const closes = bars.map((b) => b.close)
  const toT = (t: string | number) => t as Time
  if (props.sub === 'macd') {
    const { dif, dea, hist } = calcMacd(closes)
    const histS = subSeries[0] as ISeriesApi<'Histogram'>
    histS.setData(bars.map((b, i) => ({
      time: toT(b.time),
      value: hist[i] ?? 0,
      color: ((hist[i] ?? 0) >= 0 ? upColor() : downColor()) + 'b0',
    })).filter((d, i) => hist[i] != null))
    ;(subSeries[1] as ISeriesApi<'Line'>).setData(
      bars.map((b, i) => ({ time: toT(b.time), value: dif[i] })).filter((d) => d.value != null) as never,
    )
    ;(subSeries[2] as ISeriesApi<'Line'>).setData(
      bars.map((b, i) => ({ time: toT(b.time), value: dea[i] })).filter((d) => d.value != null) as never,
    )
  } else if (props.sub === 'kdj') {
    const { k, d, j } = calcKdj(bars)
    const sets = [k, d, j]
    subSeries.forEach((s, si) => {
      (s as ISeriesApi<'Line'>).setData(
        bars.map((b, i) => ({ time: toT(b.time), value: sets[si][i] })).filter((x) => x.value != null) as never,
      )
    })
  } else if (props.sub === 'rsi') {
    const sets = [calcRsi(closes, 6), calcRsi(closes, 12), calcRsi(closes, 24)]
    subSeries.forEach((s, si) => {
      (s as ISeriesApi<'Line'>).setData(
        bars.map((b, i) => ({ time: toT(b.time), value: sets[si][i] })).filter((x) => x.value != null) as never,
      )
    })
  }
}

// ---- 数据应用 ----
function apply() {
  if (!chart.value || !candleSeries.value) return
  const bars = props.bars
  if (!bars.length) return

  idxByTime = new Map(bars.map((b, i) => [String(b.time), i]))

  if (props.timeshare) {
    const avgs = timeshareAvg(bars)
    tsPriceSeries.value?.setData(bars.map((b) => ({ time: b.time as Time, value: b.close })))
    tsAvgSeries.value?.setData(bars.map((b, i) => ({ time: b.time as Time, value: +avgs[i].toFixed(3) })))
    // 昨收基准虚线
    if (tsPriceSeries.value && props.prevClose) {
      if (prevLine) { tsPriceSeries.value.removePriceLine(prevLine); prevLine = null }
      prevLine = tsPriceSeries.value.createPriceLine({
        price: props.prevClose,
        color: textColor(),
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: '昨收',
      })
    }
    candleSeries.value.setData([])
  } else {
    candleSeries.value.setData(
      bars.map((b) => ({ time: b.time as Time, open: b.open, high: b.high, low: b.low, close: b.close })),
    )
    tsPriceSeries.value?.setData([])
    tsAvgSeries.value?.setData([])
  }

  // 分时模式不画均线/布林（券商口径：分时只有价格线+均价线）
  const overlaysOn = !props.timeshare
  props.mas.forEach((n, i) => {
    const s = maSeries[i]
    if (!s) return
    if (!overlaysOn) {
      s.setData([])
      return
    }
    const data: { time: Time; value: number }[] = []
    for (let idx = 0; idx < bars.length; idx++) {
      if (idx < n - 1) continue
      let sum = 0
      for (let j = idx - n + 1; j <= idx; j++) sum += bars[j].close
      data.push({ time: bars[idx].time as Time, value: +(sum / n).toFixed(3) })
    }
    s.setData(data)
  })

  // 布林带
  if (bollSeries.value.length === 3 && (!props.boll || !overlaysOn)) {
    bollSeries.value.forEach((x) => x.setData([]))
  }
  if (props.boll && overlaysOn && bollSeries.value.length === 3) {
    const closes = bars.map((b) => b.close)
    const { mid, upper, lower } = calcBoll(closes)
    const sets = [upper, mid, lower]
    bollSeries.value.forEach((s, si) => {
      s.setData(
        bars.map((b, i) => ({ time: b.time as Time, value: sets[si][i] })).filter((d) => d.value != null) as never,
      )
    })
  }

  if (volumeSeries.value) {
    volumeSeries.value.setData(
      bars.map((b) => ({
        time: b.time as Time,
        value: b.volume ?? 0,
        color: (b.close >= b.open ? upColor() : downColor()) + '80',
      })),
    )
  }

  if (volMaSeries.value && props.volumeMa > 1) {
    const n = props.volumeMa
    const data: { time: Time; value: number }[] = []
    for (let i = n - 1; i < bars.length; i++) {
      let sum = 0
      for (let j = i - n + 1; j <= i; j++) sum += bars[j].volume ?? 0
      data.push({ time: bars[i].time as Time, value: Math.round(sum / n) })
    }
    volMaSeries.value.setData(data)
  }

  if (equitySeries.value && props.equity.length) {
    equitySeries.value.setData(props.equity.map((e) => ({ time: e.time as Time, value: e.value })))
  }

  if (fundFlowSeries.value && props.fundFlow.length) {
    fundFlowSeries.value.setData(
      props.fundFlow.map((f) => ({
        time: f.time as Time,
        value: f.mainNet,
        color: (f.mainNet >= 0 ? upColor() : downColor()) + '90',
      })),
    )
  }

  const markerData = props.markers.map((m) => ({
    time: m.time as Time,
    position: m.position,
    color: m.color,
    shape: m.shape,
    text: m.text,
  })) as SeriesMarker<Time>[]

  if (props.limitPct > 0 && !props.timeshare) {
    for (let i = 1; i < bars.length; i++) {
      const prev = bars[i - 1].close
      if (!prev) continue
      const chg = bars[i].close / prev - 1
      if (chg >= props.limitPct) {
        markerData.push({
          time: bars[i].time as Time, position: 'aboveBar', color: upColor(),
          shape: 'arrowDown', text: '涨停',
        } as SeriesMarker<Time>)
      } else if (chg <= -props.limitPct) {
        markerData.push({
          time: bars[i].time as Time, position: 'belowBar', color: downColor(),
          shape: 'arrowUp', text: '跌停',
        } as SeriesMarker<Time>)
      }
    }
    markerData.sort((a, b) => String(a.time).localeCompare(String(b.time)))
  }
  if (markersPlugin) {
    markersPlugin.setMarkers(markerData)
  } else if (candleSeries.value) {
    markersPlugin = createSeriesMarkers(candleSeries.value, markerData)
  }

  if (priceLine) {
    candleSeries.value.removePriceLine(priceLine)
    priceLine = null
  }

  chart.value.timeScale().fitContent()
  applySub()
  layoutPanes()
  schedulePlayhead()
  buildLegend(null)
}

// ---- 十字光标信息条 ----
function onCrosshair(param: MouseEventParams) {
  if (!param || param.time === undefined || !param.point) {
    buildLegend(null)
    return
  }
  buildLegend(param)
}

function fmtVol(v: number | undefined): string {
  if (v == null || !Number.isFinite(v)) return '—'
  if (Math.abs(v) >= 1e8) return (v / 1e8).toFixed(2) + '亿'
  if (Math.abs(v) >= 1e4) return (v / 1e4).toFixed(2) + '万'
  return String(Math.round(v))
}

function buildLegend(param: MouseEventParams | null) {
  const bars = props.bars
  if (!bars.length) { legendRows.value = []; return }
  let idx = bars.length - 1
  if (param && param.time !== undefined) {
    const i = idxByTime.get(String(param.time))
    if (i != null) idx = i
  }
  const b = bars[idx]
  const prevClose = idx > 0 ? bars[idx - 1].close : (props.prevClose ?? b.open)
  const base = props.timeshare ? (props.prevClose ?? prevClose) : prevClose
  const chg = base ? (b.close / base - 1) * 100 : 0
  // 分时看全天：高低/振幅用当日全部分钟的极值，而不是当前这一分钟
  let hi = b.high
  let lo = b.low
  let vol = b.volume
  let amt = b.amount
  if (props.timeshare) {
    // 分时看全天：高低/振幅/量/额都取当日累计，而不是当前这一分钟
    let v = 0
    let a = 0
    for (const x of bars) {
      if (x.high > hi) hi = x.high
      if (x.low < lo) lo = x.low
      v += x.volume ?? 0
      a += x.amount ?? 0
    }
    vol = v
    amt = a
  }
  const amp = base ? ((hi - lo) / base) * 100 : 0
  const cUp = chg >= 0 ? upColor() : downColor()

  const rows: LegendCell[][] = []
  rows.push([
    { label: '开', value: (props.timeshare ? (bars[0]?.open ?? b.open) : b.open).toFixed(2) },
    { label: '高', value: hi.toFixed(2) },
    { label: '低', value: lo.toFixed(2) },
    { label: '收', value: b.close.toFixed(2) },
    { label: '涨跌', value: `${b.close - base >= 0 ? '+' : ''}${(b.close - base).toFixed(2)}`, color: cUp },
    { label: '涨跌幅', value: `${chg >= 0 ? '+' : ''}${chg.toFixed(2)}%`, color: cUp },
    { label: '振幅', value: `${amp.toFixed(2)}%` },
    { label: '量', value: fmtVol(vol) },
    ...(amt ? [{ label: '额', value: fmtVol(amt) }] : []),
  ])

  if (props.timeshare) {
    const avgs = timeshareAvg(bars)
    rows[0].push({ label: '均价', value: (avgs[idx] ?? b.close).toFixed(2), color: tokens().gold })
  } else if (props.mas.length) {
    const row: LegendCell[] = []
    props.mas.forEach((n, i) => {
      if (idx < n - 1) return
      let sum = 0
      for (let j = idx - n + 1; j <= idx; j++) sum += bars[j].close
      row.push({ label: `MA${n}`, value: (sum / n).toFixed(2), color: maColor(i) })
    })
    if (row.length) rows.push(row)
  }

  if (props.boll && !props.timeshare) {
    const closes = bars.map((x) => x.close)
    const { mid, upper, lower } = calcBoll(closes)
    if (mid[idx] != null) {
      rows.push([
        { label: 'BOLL', value: mid[idx]!.toFixed(2), color: tokens().textSub },
        { label: 'UP', value: upper[idx]!.toFixed(2), color: withAlpha(tokens().textSub, 0.9) },
        { label: 'LB', value: lower[idx]!.toFixed(2), color: withAlpha(tokens().textSub, 0.9) },
      ])
    }
  }

  if (props.sub !== 'none') {
    const closes = bars.map((x) => x.close)
    if (props.sub === 'macd') {
      const { dif, dea, hist } = calcMacd(closes)
      rows.push([
        { label: 'MACD', value: 'DIF ' + (dif[idx]?.toFixed(3) ?? '—'), color: maColors()[0] },
        { label: 'DEA', value: dea[idx]?.toFixed(3) ?? '—', color: maColors()[1] },
        { label: 'MACD', value: hist[idx]?.toFixed(3) ?? '—', color: (hist[idx] ?? 0) >= 0 ? upColor() : downColor() },
      ])
    } else if (props.sub === 'kdj') {
      const { k, d, j } = calcKdj(bars)
      rows.push([
        { label: 'K', value: k[idx]?.toFixed(2) ?? '—', color: maColors()[0] },
        { label: 'D', value: d[idx]?.toFixed(2) ?? '—', color: maColors()[1] },
        { label: 'J', value: j[idx]?.toFixed(2) ?? '—', color: maColors()[2] },
      ])
    } else if (props.sub === 'rsi') {
      const r6 = calcRsi(closes, 6); const r12 = calcRsi(closes, 12); const r24 = calcRsi(closes, 24)
      rows.push([
        { label: 'RSI6', value: r6[idx]?.toFixed(2) ?? '—', color: maColors()[0] },
        { label: 'RSI12', value: r12[idx]?.toFixed(2) ?? '—', color: maColors()[1] },
        { label: 'RSI24', value: r24[idx]?.toFixed(2) ?? '—', color: maColors()[2] },
      ])
    }
  }

  legendRows.value = rows
}

// ---- 工具 ----
function zoom(factor: number) {
  const ts = chart.value?.timeScale()
  if (!ts) return
  const r = ts.getVisibleLogicalRange()
  if (!r) return
  const mid = (r.from + r.to) / 2
  const half = ((r.to - r.from) / 2) * factor
  ts.setVisibleLogicalRange({ from: mid - half, to: mid + half })
}
function resetView() {
  chart.value?.timeScale().fitContent()
}
function screenshot() {
  const src = chart.value?.takeScreenshot()
  if (!src) return
  const titleH = 30
  const out = document.createElement('canvas')
  out.width = src.width
  out.height = src.height + titleH
  const ctx = out.getContext('2d')
  if (!ctx) return
  const bg = cssVar('--bg-panel', '#14171C')
  ctx.fillStyle = bg
  ctx.fillRect(0, 0, out.width, out.height)
  ctx.fillStyle = cssVar('--text', '#E5E7EB')
  ctx.font = '600 14px system-ui, sans-serif'
  ctx.textBaseline = 'middle'
  ctx.fillText(props.title || 'K线图', 12, titleH / 2)
  ctx.fillStyle = cssVar('--text-faint', '#6B7280')
  ctx.font = '11px system-ui, sans-serif'
  const stamp = new Date().toLocaleString('zh-CN')
  ctx.fillText(stamp, out.width - ctx.measureText(stamp).width - 12, titleH / 2)
  ctx.drawImage(src, 0, titleH)
  out.toBlob((blob) => {
    if (!blob) return
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `${(props.title || 'kline').replace(/[\\/:*?"<>|]/g, '_')}-${Date.now()}.png`
    a.click()
    URL.revokeObjectURL(a.href)
  })
}
async function toggleFs() {
  if (!document.fullscreenElement) {
    await wrapEl.value?.requestFullscreen?.()
  } else {
    await document.exitFullscreen?.()
  }
}
function onFsChange() {
  isFs.value = !!document.fullscreenElement
  nextTick(() => {
    const h = isFs.value ? (el.value?.clientHeight || window.innerHeight) : props.height
    chart.value?.applyOptions({ width: el.value?.clientWidth, height: h })
    layoutPanes()
  })
}

function schedulePlayhead() {
  rangeTick.value++
  cancelAnimationFrame(rafId)
  rafId = requestAnimationFrame(positionPlayhead)
}

function positionPlayhead() {
  const line = playheadEl.value
  if (!line || !chart.value) return
  if (!props.playheadTime) {
    line.style.display = 'none'
    return
  }
  const x = chart.value.timeScale().timeToCoordinate(props.playheadTime as Time)
  if (x == null) {
    line.style.display = 'none'
    return
  }
  line.style.display = 'block'
  line.style.left = `${x}px`
}

function applyTheme() {
  if (!chart.value) return
  chart.value.applyOptions({
    layout: { textColor: textColor() },
    grid: { vertLines: { color: gridColor() }, horzLines: { color: gridColor() } },
    rightPriceScale: { borderColor: borderColor() },
    timeScale: { borderColor: borderColor() },
  })
  candleSeries.value?.applyOptions({
    upColor: upColor(),
    downColor: downColor(),
    borderUpColor: upColor(),
    borderDownColor: downColor(),
    wickUpColor: upColor(),
    wickDownColor: downColor(),
  })
  maSeries.forEach((s, i) => s.applyOptions({ color: maColor(i) }))
  bollSeries.value.forEach((s, k) => s.applyOptions({
    color: k === 1 ? tokens().textSub : withAlpha(tokens().textSub, 0.66),
  }))
  volMaSeries.value?.applyOptions({ color: tokens().textSub })
  tsAvgSeries.value?.applyOptions({ color: tokens().gold })
  if (volumeSeries.value) {
    volumeSeries.value.setData(
      props.bars.map((b) => ({
        time: b.time as Time,
        value: b.volume ?? 0,
        color: (b.close >= b.open ? upColor() : downColor()) + '80',
      })),
    )
  }
  if (fundFlowSeries.value && props.fundFlow.length) {
    fundFlowSeries.value.setData(
      props.fundFlow.map((f) => ({
        time: f.time as Time,
        value: f.mainNet,
        color: (f.mainNet >= 0 ? upColor() : downColor()) + '90',
      })),
    )
  }
  {
    const line = cssVar('--accent', '#7AA2F7')
    equitySeries.value?.applyOptions({
      lineColor: line,
      topColor: withAlpha(line, 0.28),
      bottomColor: withAlpha(line, 0.02),
    })
    tsPriceSeries.value?.applyOptions({
      lineColor: line,
      topColor: withAlpha(line, 0.22),
      bottomColor: withAlpha(line, 0.02),
    })
  }
  applySub()
  buildLegend(null)
}

/** 均线组变化：重建均线序列 */
function rebuildMas() {
  if (!chart.value) return
  maSeries.forEach((s) => chart.value!.removeSeries(s))
  maSeries = []
  props.mas.forEach((_, i) => {
    const s = chart.value!.addSeries(LineSeries, {
      color: maColor(i),
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    })
    maSeries.push(s)
  })
  apply()
}

watch(() => props.bars, () => apply())
watch(() => props.markers, () => apply())
watch(() => props.playheadTime, () => schedulePlayhead())
watch(() => props.height, (h) => {
  if (!isFs.value) chart.value?.applyOptions({ height: h })
})
watch(() => props.fundFlow, () => { syncStructure(); apply() })
watch(() => [props.showFundFlow, props.showEquity, props.equity], () => syncStructure())
watch(() => props.sub, () => { ensureSub(); buildLegend(null) })
watch(() => props.boll, (on) => {
  bollSeries.value.forEach((s) => s.applyOptions({ visible: on }))
  if (on) apply()
  buildLegend(null)
})
watch(() => props.timeshare, (on) => {
  candleSeries.value?.applyOptions({ visible: !on })
  tsPriceSeries.value?.applyOptions({ visible: on })
  tsAvgSeries.value?.applyOptions({ visible: on })
  chart.value?.timeScale().applyOptions({ timeVisible: props.intraday || on })
  apply()
})
watch(() => props.intraday, (on) => chart.value?.timeScale().applyOptions({ timeVisible: on || props.timeshare }))
watch(() => props.mas, () => rebuildMas())

onMounted(init)
onBeforeUnmount(() => {
  cancelAnimationFrame(rafId)
  ro?.disconnect()
  mo?.disconnect()
  document.removeEventListener('fullscreenchange', onFsChange)
  chart.value?.remove()
})
</script>

<template>
  <div
    ref="wrapEl"
    class="lwc-wrap"
    tabindex="0"
    :data-panes="paneCount"
    :class="{ 'lwc-wrap--fs': isFs, 'lwc-wrap--measure': measureOn }"
    :style="isFs ? {} : { height: `${height}px` }"
    @keydown="onKey"
    @pointerdown="onWrapPointerDown"
  >
    <div v-if="showLegend && legendRows.length" class="lwc-legend">
      <div v-for="(row, ri) in legendRows" :key="ri" class="lwc-legend__row">
        <span v-for="c in row" :key="c.label + c.value" class="lwc-legend__cell">
          <span class="lwc-legend__lbl">{{ c.label }}</span>
          <span class="lwc-legend__val" :style="c.color ? { color: c.color } : undefined">{{ c.value }}</span>
        </span>
      </div>
    </div>
    <div ref="el" class="lwc-chart" />
    <div v-if="selRect" class="lwc-sel" :style="{ left: `${selRect.left}px`, width: `${selRect.width}px` }" />
    <div v-if="sel" class="lwc-selstats">
      <div class="lwc-selstats__row lwc-selstats__row--head">{{ sel.stats.from }} → {{ sel.stats.to }} · {{ sel.stats.n }} 根</div>
      <div class="lwc-selstats__row">
        <span>涨跌幅</span>
        <b :class="sel.stats.chg >= 0 ? 'up' : 'down'">{{ (sel.stats.chg >= 0 ? '+' : '') + sel.stats.chg.toFixed(2) }}%</b>
        <span class="sep">·</span><span>振幅</span><b>{{ sel.stats.amp.toFixed(2) }}%</b>
      </div>
      <div class="lwc-selstats__row">
        <span>高</span><b>{{ sel.stats.hi.toFixed(2) }}</b>
        <span class="sep">·</span><span>低</span><b>{{ sel.stats.lo.toFixed(2) }}</b>
      </div>
      <div class="lwc-selstats__row">
        <span>量</span><b>{{ fmtVol(sel.stats.vol) }}</b>
        <span class="sep">·</span><span>额</span><b>{{ fmtVol(sel.stats.amt) }}</b>
      </div>
    </div>
    <div ref="playheadEl" class="lwc-playhead" :style="{ background: playheadColor }" />
    <div v-if="showTools" class="lwc-tools">
      <button
        class="lwc-tool" :class="{ 'is-on': measureOn }"
        title="区间测量（拖拽选择，Esc 退出）" @click="toggleMeasure"
      ><Icon name="ruler" :size="13" /></button>
      <button class="lwc-tool" title="放大" @click="zoom(0.7)"><Icon name="plus" :size="13" /></button>
      <button class="lwc-tool" title="缩小" @click="zoom(1.4)"><Icon name="minus" :size="13" /></button>
      <button class="lwc-tool" title="复位" @click="resetView"><Icon name="refresh" :size="13" /></button>
      <button class="lwc-tool" title="截图" @click="screenshot"><Icon name="download" :size="13" /></button>
      <button class="lwc-tool" :title="isFs ? '退出全屏' : '全屏'" @click="toggleFs">
        <Icon :name="isFs ? 'restore' : 'maximize'" :size="13" />
      </button>
    </div>
  </div>
</template>

<style scoped>
.lwc-wrap { position: relative; width: 100%; outline: none; }
.lwc-wrap:focus-visible { box-shadow: 0 0 0 2px var(--ring, rgba(122, 162, 247, 0.45)); border-radius: var(--radius-sm, 6px); }
.lwc-wrap--measure { cursor: crosshair; }
.lwc-wrap:fullscreen { height: 100vh !important; background: var(--bg); }

.lwc-sel {
  position: absolute;
  top: 0;
  bottom: 28px;
  z-index: 2;
  pointer-events: none;
  background: color-mix(in srgb, var(--accent) 13%, transparent);
  border-left: 1px dashed var(--accent);
  border-right: 1px dashed var(--accent);
}
.lwc-selstats {
  position: absolute;
  left: 10px;
  bottom: 36px;
  z-index: 3;
  pointer-events: none;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 8px 10px;
  border-radius: var(--radius-md, 8px);
  border: 1px solid var(--border-soft);
  background: color-mix(in srgb, var(--bg-panel) 92%, transparent);
  font-size: 11px;
  line-height: 1.5;
  font-variant-numeric: tabular-nums;
  box-shadow: var(--shadow-1, 0 2px 8px rgba(0, 0, 0, 0.2));
}
.lwc-selstats__row { display: flex; align-items: baseline; gap: 5px; }
.lwc-selstats__row span { color: var(--text-faint); }
.lwc-selstats__row b { color: var(--text); font-weight: 600; }
.lwc-selstats__row--head { color: var(--accent); font-weight: 600; }
.lwc-selstats__row .sep { color: var(--border-strong); }
.lwc-selstats .up { color: var(--up); }
.lwc-selstats .down { color: var(--down); }
.lwc-chart { width: 100%; height: 100%; }

.lwc-legend {
  position: absolute;
  left: 8px;
  top: 6px;
  z-index: 3;
  pointer-events: none;
  display: flex;
  flex-direction: column;
  gap: 1px;
  font-size: 11px;
  line-height: 1.5;
  font-variant-numeric: tabular-nums;
  max-width: calc(100% - 130px);
}
.lwc-legend__row { display: flex; flex-wrap: wrap; gap: 0 10px; }
.lwc-legend__cell { white-space: nowrap; }
.lwc-legend__lbl { color: var(--text-faint); margin-right: 3px; }
.lwc-legend__val { color: var(--text-sub); font-weight: 600; }

.lwc-playhead {
  position: absolute;
  top: 0;
  bottom: 22px;
  width: 1px;
  pointer-events: none;
  opacity: 0.85;
  display: none;
}

.lwc-tools {
  position: absolute;
  right: 8px;
  top: 6px;
  z-index: 3;
  display: flex;
  gap: 3px;
  opacity: 0.7;
  transition: opacity var(--dur-fast) var(--ease);
}
.lwc-wrap:hover .lwc-tools { opacity: 1; }
.lwc-tool {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: var(--radius-sm, 6px);
  border: 1px solid var(--border-soft);
  background: var(--bg-raised);
  color: var(--text-sub);
  cursor: pointer;
  padding: 0;
  transition: color var(--dur-fast) var(--ease), border-color var(--dur-fast) var(--ease);
}
.lwc-tool:hover { color: var(--accent); border-color: var(--accent); }
.lwc-tool.is-on { color: var(--on-gold, #1a1d23); background: var(--gold); border-color: var(--gold); }
</style>
