<script setup lang="ts">
import { ref, watch, onMounted, onBeforeUnmount, shallowRef } from 'vue'
import * as echarts from 'echarts/core'
import { CandlestickChart, BarChart, LineChart } from 'echarts/charts'
import {
  TooltipComponent,
  GridComponent,
  DataZoomComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { KlineBar } from '@/api'
import { chartTokens, maColors } from '@/lib/chartTheme'
import { cssVar } from '@/composables/useEChart'

echarts.use([
  CandlestickChart, BarChart, LineChart,
  TooltipComponent, GridComponent, DataZoomComponent,
  CanvasRenderer,
])

const props = defineProps<{ bars: KlineBar[] }>()

const el = ref<HTMLDivElement>()
const chart = shallowRef<echarts.ECharts>()

function getTheme() {
  return document.documentElement.getAttribute('data-theme') || 'graphite'
}

function buildOption(bars: KlineBar[]): echarts.EChartsCoreOption {
  const isDark = getTheme() !== 'ivory'
  const upColor = cssVar('--up', '#E84040')
  const downColor = cssVar('--down', '#2DB757')
  const _t = chartTokens()
  const gridText = _t.textSub
  const gridLine = _t.borderSoft
  const maCol = maColors()

  const dates = bars.map((b) => b.date)
  const ohlc = bars.map((b) => [b.open, b.close, b.low, b.high])
  const volumes = bars.map((b) => b.volume)
  const colors = bars.map((b) => (b.close >= b.open ? upColor : downColor))

  const ma = (n: number) =>
    bars.map((_, i) => {
      if (i < n - 1) return null
      let sum = 0
      for (let j = i - n + 1; j <= i; j++) sum += bars[j].close
      return +(sum / n).toFixed(2)
    })

  return {
    animation: false,
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross', lineStyle: { color: gridLine } },
      backgroundColor: _t.glass,
      extraCssText: 'backdrop-filter: blur(8px); border-radius: 8px; box-shadow: 0 8px 24px rgba(0,0,0,.28);',
      borderColor: _t.border,
      textStyle: { color: _t.text, fontSize: 12 },
      formatter(params: unknown) {
        if (!Array.isArray(params) || !params.length) return ''
        const p = params[0] as { data: number[]; axisValue: string }
        const [o, c, l, h] = p.data
        const chg = o ? ((c - o) / o * 100).toFixed(2) : '0.00'
        const color = c >= o ? upColor : downColor
        return `<div style="font-size:12px">
          <div style="margin-bottom:4px;color:${gridText}">${p.axisValue}</div>
          <div>开 <b>${o}</b> 收 <b style="color:${color}">${c}</b></div>
          <div>低 <b>${l}</b> 高 <b>${h}</b></div>
          <div>涨跌 <b style="color:${color}">${chg}%</b></div>
        </div>`
      },
    },
    axisPointer: { link: [{ xAxisIndex: [0, 1] }] },
    grid: [
      { left: 60, right: 20, top: 20, height: '58%' },
      { left: 60, right: 20, top: '76%', height: '14%' },
    ],
    xAxis: [
      {
        type: 'category', data: dates, gridIndex: 0,
        axisLine: { lineStyle: { color: gridLine } },
        axisLabel: { show: false },
        splitLine: { show: false },
      },
      {
        type: 'category', data: dates, gridIndex: 1,
        axisLine: { lineStyle: { color: gridLine } },
        axisLabel: { color: gridText, fontSize: 10 },
        splitLine: { show: false },
      },
    ],
    yAxis: [
      {
        type: 'value', gridIndex: 0, scale: true,
        splitLine: { lineStyle: { color: gridLine, type: 'dashed' } },
        axisLabel: { color: gridText, fontSize: 10 },
      },
      {
        type: 'value', gridIndex: 1, scale: true,
        splitNumber: 2,
        axisLabel: { show: false },
        splitLine: { show: false },
      },
    ],
    dataZoom: [
      { type: 'inside', xAxisIndex: [0, 1], start: 60, end: 100 },
    ],
    series: [
      {
        type: 'candlestick',
        xAxisIndex: 0, yAxisIndex: 0,
        data: ohlc,
        itemStyle: {
          color: upColor,
          color0: downColor,
          borderColor: upColor,
          borderColor0: downColor,
        },
      },
      { name: 'MA5', type: 'line', xAxisIndex: 0, yAxisIndex: 0, data: ma(5), smooth: true, symbol: 'none', lineStyle: { width: 1, color: maCol[0] } },
      { name: 'MA10', type: 'line', xAxisIndex: 0, yAxisIndex: 0, data: ma(10), smooth: true, symbol: 'none', lineStyle: { width: 1, color: maCol[1] } },
      { name: 'MA20', type: 'line', xAxisIndex: 0, yAxisIndex: 0, data: ma(20), smooth: true, symbol: 'none', lineStyle: { width: 1, color: maCol[2] } },
      {
        type: 'bar',
        xAxisIndex: 1, yAxisIndex: 1,
        data: volumes.map((v, i) => ({ value: v, itemStyle: { color: colors[i] + '88' } })),
        barMaxWidth: 8,
      },
    ],
  }
}

function init() {
  if (!el.value) return
  chart.value = echarts.init(el.value, undefined, { renderer: 'canvas' })
  if (props.bars.length) chart.value.setOption(buildOption(props.bars))
}

watch(() => props.bars, (b) => {
  if (chart.value && b.length) chart.value.setOption(buildOption(b), true)
}, { deep: false })

const ro = typeof ResizeObserver !== 'undefined'
  ? new ResizeObserver(() => chart.value?.resize())
  : null
let mo: MutationObserver | null = null

onMounted(() => {
  init()
  if (ro && el.value) ro.observe(el.value)
  mo = new MutationObserver(() => {
    if (chart.value && props.bars.length) chart.value.setOption(buildOption(props.bars), true)
  })
  mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
})

onBeforeUnmount(() => {
  ro?.disconnect()
  mo?.disconnect()
  chart.value?.dispose()
})
</script>

<template>
  <div ref="el" class="kline-chart"></div>
</template>

<style scoped>
.kline-chart {
  width: 100%;
  height: 480px;
  min-height: 360px;
}
</style>
