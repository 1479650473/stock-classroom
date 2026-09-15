<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import {
  createChart, CandlestickSeries, HistogramSeries, LineSeries, AreaSeries, LineStyle, CrosshairMode,
  createSeriesMarkers,
} from 'lightweight-charts'
import type {
  IChartApi, ISeriesApi, Time, SeriesMarker, IPriceLine, ISeriesMarkersPluginApi,
} from 'lightweight-charts'
import { cssVar } from '@/composables/useEChart'
import { chartTokens, maColors, withAlpha } from '@/lib/chartTheme'

/** 轻量专业 K 线：TradingView Lightweight Charts v5 封装 */
export interface LwcBar {
  time: string
  open: number
  high: number
  low: number
  close: number
  volume?: number
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

const props = withDefaults(
  defineProps<{
    bars: LwcBar[]
    /** 均线周期 */
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
    /** 权益曲线（独立 pane） */
    equity?: { time: string; value: number }[]
    /** 资金流副图（主力净流入柱状, 独立 pane） */
    fundFlow?: LwcFundFlow[]
    /** 涨跌停判定阈值（0.098 主板 / 0.198 创业科创 / 0.048 ST）；0 = 不标记 */
    limitPct?: number
    /** 成交量均线周期（0 = 不画） */
    volumeMa?: number
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
    fundFlow: () => [],
    limitPct: 0,
    volumeMa: 5,
  },
)

const el = ref<HTMLDivElement>()
const playheadEl = ref<HTMLDivElement>()
const chart = shallowRef<IChartApi | null>(null)
const candleSeries = shallowRef<ISeriesApi<'Candlestick'> | null>(null)
const volumeSeries = shallowRef<ISeriesApi<'Histogram'> | null>(null)
const equitySeries = shallowRef<ISeriesApi<'Area'> | null>(null)
const fundFlowSeries = shallowRef<ISeriesApi<'Histogram'> | null>(null)
const volMaSeries = shallowRef<ISeriesApi<'Line'> | null>(null)
const maSeries: ISeriesApi<'Line'>[] = []
let priceLine: IPriceLine | null = null
let markersPlugin: ISeriesMarkersPluginApi<Time> | null = null
let ro: ResizeObserver | null = null
let mo: MutationObserver | null = null
let rafId = 0

function tokens() { return chartTokens() }
function textColor() { return tokens().textSub }
function gridColor() { return tokens().borderSoft }
function borderColor() { return tokens().border }
function upColor() { return tokens().up }
function downColor() { return tokens().down }
function maColor(i: number) { return maColors()[i % maColors().length] }

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
    timeScale: { borderColor: borderColor(), timeVisible: false, rightOffset: 2 },
  })

  candleSeries.value = chart.value.addSeries(CandlestickSeries, {
    upColor: upColor(),
    downColor: downColor(),
    borderUpColor: upColor(),
    borderDownColor: downColor(),
    wickUpColor: upColor(),
    wickDownColor: downColor(),
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

  if (props.equity.length) {
    const line = cssVar('--accent', '#7AA2F7')
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

  if (props.fundFlow.length) {
    fundFlowSeries.value = chart.value.addSeries(
      HistogramSeries,
      { priceFormat: { type: 'volume' }, priceLineVisible: false, lastValueVisible: false },
      3,
    )
  }

  ro = new ResizeObserver(() => {
    if (chart.value && el.value) {
      chart.value.applyOptions({ width: el.value.clientWidth })
      schedulePlayhead()
    }
  })
  ro.observe(el.value)

  mo = new MutationObserver(() => applyTheme())
  mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })

  chart.value.timeScale().subscribeVisibleTimeRangeChange(schedulePlayhead)

  apply()
}

function apply() {
  if (!chart.value || !candleSeries.value) return
  const bars = props.bars
  if (!bars.length) return

  candleSeries.value.setData(
    bars.map((b) => ({ time: b.time as Time, open: b.open, high: b.high, low: b.low, close: b.close })),
  )

  props.mas.forEach((n, i) => {
    const s = maSeries[i]
    if (!s) return
    const data: { time: Time; value: number }[] = []
    for (let idx = 0; idx < bars.length; idx++) {
      if (idx < n - 1) continue
      let sum = 0
      for (let j = idx - n + 1; j <= idx; j++) sum += bars[j].close
      data.push({ time: bars[idx].time as Time, value: +(sum / n).toFixed(2) })
    }
    s.setData(data)
  })

  if (volumeSeries.value) {
    volumeSeries.value.setData(
      bars.map((b) => ({
        time: b.time as Time,
        value: b.volume ?? 0,
        color: (b.close >= b.open ? upColor() : downColor()) + '80',
      })),
    )
  }

  // 成交量均线：量的 5 日均线，滤掉单日放量噪音
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

  // 涨跌停自动标记（limitPct>0 时生效）：主板 9.8% / 创业科创 19.8% / ST 4.8%
  if (props.limitPct > 0) {
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
  schedulePlayhead()
}

function schedulePlayhead() {
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
  // 均线 / 量柱 / 资金流 / 权益线也要跟着主题重刷，否则切换后仍留旧配色
  maSeries.forEach((s, i) => s.applyOptions({ color: maColor(i) }))
  volMaSeries.value?.applyOptions({ color: tokens().textSub })
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
  }
}

watch(() => props.bars, () => apply())
watch(() => props.markers, () => apply())
watch(() => props.playheadTime, () => schedulePlayhead())
watch(() => props.height, (h) => chart.value?.applyOptions({ height: h }))
watch(() => props.fundFlow, () => apply())

onMounted(init)
onBeforeUnmount(() => {
  cancelAnimationFrame(rafId)
  ro?.disconnect()
  mo?.disconnect()
  chart.value?.remove()
})
</script>

<template>
  <div class="lwc-wrap" :style="{ height: `${height}px` }">
    <div ref="el" class="lwc-chart" />
    <div ref="playheadEl" class="lwc-playhead" :style="{ background: playheadColor }" />
  </div>
</template>

<style scoped>
.lwc-wrap { position: relative; width: 100%; }
.lwc-chart { width: 100%; height: 100%; }
.lwc-playhead {
  position: absolute;
  top: 0;
  bottom: 22px;
  width: 1px;
  pointer-events: none;
  opacity: 0.85;
  display: none;
}
</style>
