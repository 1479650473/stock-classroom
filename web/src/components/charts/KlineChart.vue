<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import {
  createChart, CandlestickSeries, HistogramSeries, LineSeries, LineStyle, CrosshairMode, createSeriesMarkers,
} from 'lightweight-charts'
import type {
  IChartApi, ISeriesApi, Time, SeriesMarker, IPriceLine, ISeriesMarkersPluginApi,
} from 'lightweight-charts'
import { cssVar } from '@/composables/useEChart'

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
  },
)

const el = ref<HTMLDivElement>()
const playheadEl = ref<HTMLDivElement>()
const chart = shallowRef<IChartApi | null>(null)
const candleSeries = shallowRef<ISeriesApi<'Candlestick'> | null>(null)
const volumeSeries = shallowRef<ISeriesApi<'Histogram'> | null>(null)
const equitySeries = shallowRef<ISeriesApi<'Line'> | null>(null)
const maSeries: ISeriesApi<'Line'>[] = []
let priceLine: IPriceLine | null = null
let markersPlugin: ISeriesMarkersPluginApi<Time> | null = null
let ro: ResizeObserver | null = null
let mo: MutationObserver | null = null
let rafId = 0

const MA_COLORS = ['#E8B84B', '#C16BE0', '#5B8FF9', '#F97316']

function isDark() { return document.documentElement.getAttribute('data-theme') !== 'ivory' }
function textColor() { return isDark() ? '#9AA3B0' : '#666666' }
function gridColor() { return isDark() ? '#1d222a' : '#ece5d8' }
function borderColor() { return isDark() ? '#232830' : '#e2dbcc' }
function upColor() { return cssVar('--up', '#E5484D') }
function downColor() { return cssVar('--down', '#3FB950') }

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
    crosshair: { mode: CrosshairMode.Normal },
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
      color: MA_COLORS[i % MA_COLORS.length],
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
  }

  if (props.equity.length) {
    equitySeries.value = chart.value.addSeries(
      LineSeries,
      {
        color: cssVar('--info', '#7AA2F7'),
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: false,
      },
      2,
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

  if (equitySeries.value && props.equity.length) {
    equitySeries.value.setData(props.equity.map((e) => ({ time: e.time as Time, value: e.value })))
  }

  const markerData = props.markers.map((m) => ({
    time: m.time as Time,
    position: m.position,
    color: m.color,
    shape: m.shape,
    text: m.text,
  })) as SeriesMarker<Time>[]
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
}

watch(() => props.bars, () => apply())
watch(() => props.markers, () => apply())
watch(() => props.playheadTime, () => schedulePlayhead())
watch(() => props.height, (h) => chart.value?.applyOptions({ height: h }))

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
