<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref, watch, nextTick } from 'vue'
import * as echarts from 'echarts/core'
import { CandlestickChart, BarChart, LineChart, ScatterChart, CustomChart } from 'echarts/charts'
import {
  TooltipComponent, GridComponent, DataZoomComponent, MarkPointComponent, MarkAreaComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import PageHeader from '@/components/PageHeader.vue'
import Card from '@/components/Card.vue'
import EmptyState from '@/components/EmptyState.vue'
import { getKline, searchStock, getReplayStrategies, getReplay } from '@/api'
import type { KlineBar, ReplayStrategy, ReplayResult, StockRef } from '@/api'
import { cssVar } from '@/composables/useEChart'

echarts.use([
  CandlestickChart, BarChart, LineChart, ScatterChart, CustomChart,
  TooltipComponent, GridComponent, DataZoomComponent, MarkPointComponent, MarkAreaComponent,
  CanvasRenderer,
])

const bars = ref<KlineBar[]>([])
const strategies = ref<ReplayStrategy[]>([])
const replay = ref<ReplayResult | null>(null)

const code = ref('600036')
const name = ref('')
const strategyId = ref('')
const days = ref(500)
const loading = ref(false)
const errorMsg = ref('')

// 搜索
const searchResults = ref<StockRef[]>([])
const searchOpen = ref(false)
const searchLoading = ref(false)
let searchTimer: ReturnType<typeof setTimeout> | null = null

// 播放控制
const cursor = ref(0)
const playing = ref(false)
const speed = ref(600) // ms/bar
let playTimer: ReturnType<typeof setInterval> | null = null

const el = ref<HTMLDivElement>()
const chart = ref<echarts.ECharts | null>(null)

const isDark = computed(() => document.documentElement.getAttribute('data-theme') !== 'ivory')

function doSearch(q: string) {
  if (searchTimer) clearTimeout(searchTimer)
  if (!q.trim()) { searchResults.value = []; return }
  searchTimer = setTimeout(async () => {
    searchLoading.value = true
    try { searchResults.value = await searchStock(q.trim()) }
    catch { searchResults.value = [] }
    finally { searchLoading.value = false }
  }, 250)
}

function pickStock(s: StockRef) {
  code.value = s.code
  name.value = s.name
  searchOpen.value = false
  searchResults.value = []
  load()
}

async function loadStrategies() {
  try { strategies.value = await getReplayStrategies() } catch { strategies.value = [] }
}

async function load() {
  if (!code.value) return
  loading.value = true
  errorMsg.value = ''
  playing.value = false
  if (playTimer) { clearInterval(playTimer); playTimer = null }
  try {
    bars.value = await getKline(code.value, days.value)
    if (strategies.value.length === 0) await loadStrategies()
    if (strategyId.value && bars.value.length) {
      await loadReplay()
    } else {
      replay.value = null
      cursor.value = 0
    }
  } catch (e) {
    errorMsg.value = e instanceof Error ? e.message : '加载失败'
    bars.value = []
  } finally {
    loading.value = false
  }
}

async function loadReplay() {
  if (!code.value || !strategyId.value) return
  try {
    replay.value = await getReplay(code.value, strategyId.value, days.value)
    cursor.value = 0
    renderChart()
  } catch (e) {
    errorMsg.value = e instanceof Error ? e.message : '回放加载失败'
    replay.value = null
  }
}

function buildOption(): echarts.EChartsCoreOption {
  const upColor = cssVar('--up', '#E84040')
  const downColor = cssVar('--down', '#2DB757')
  const gridText = isDark.value ? '#8A8F9A' : '#666'
  const gridLine = isDark.value ? '#2A2D35' : '#E5E7EB'
  const gold = cssVar('--gold', '#D4A574')

  const dates = bars.value.map((b) => b.date)
  const ohlc = bars.value.map((b) => [b.open, b.close, b.low, b.high])
  const volumes = bars.value.map((b) => b.volume)
  const colors = bars.value.map((b) => (b.close >= b.open ? upColor : downColor))

  const ma = (n: number) =>
    bars.value.map((_, i) => {
      if (i < n - 1) return null
      let sum = 0
      for (let j = i - n + 1; j <= i; j++) sum += bars.value[j].close
      return +(sum / n).toFixed(2)
    })

  // 买卖点
  const markPoints: { coord: [number, number]; value: string; symbol: string; symbolSize: number; itemStyle: { color: string } }[] = []
  // 持仓区间(绿色半透明带)
  const markAreas: Array<Array<{ xAxis: number; itemStyle?: { color: string } }>> = []

  if (replay.value) {
    const entries = replay.value.events.filter((e) => e.kind === 'entry')
    const exits = replay.value.events.filter((e) => e.kind === 'exit')
    for (const e of entries) {
      if (e.index >= dates.length) continue
      markPoints.push({ coord: [e.index, e.price], value: 'B', symbol: 'pin', symbolSize: 26, itemStyle: { color: '#2DB757' } })
    }
    for (const e of exits) {
      if (e.index >= dates.length) continue
      markPoints.push({ coord: [e.index, e.price], value: 'S', symbol: 'pin', symbolSize: 26, itemStyle: { color: '#E84040' } })
    }
    // 持仓区间高亮带(用 markArea 的矩形: [{xAxis, yAxis}*2])
    for (const [s, e] of replay.value.holding_spans) {
      if (s >= dates.length) continue
      const endIdx = Math.min(e, dates.length - 1)
      if (endIdx < s) continue
      markAreas.push([{ xAxis: s, itemStyle: { color: 'rgba(45,183,87,0.14)' } }, { xAxis: endIdx }])
    }
  }

  const c = cursor.value
  const visible = Math.min(160, bars.value.length)
  const start = Math.max(0, Math.min(c - Math.floor(visible * 0.6), bars.value.length - visible))

  return {
    animation: false,
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross', lineStyle: { color: gridLine } },
      backgroundColor: isDark.value ? '#1A1D23EE' : '#FFFFFFEE',
      borderColor: isDark.value ? '#2A2D35' : '#E5E7EB',
      textStyle: { color: isDark.value ? '#D4D7DC' : '#333', fontSize: 12 },
      formatter(params: unknown) {
        if (!Array.isArray(params) || !params.length) return ''
        const p = params[0] as { dataIndex: number; data: number[]; axisValue: string }
        const b = bars.value[p.dataIndex]
        if (!b) return ''
        const chg = ((b.close - b.open) / b.open * 100).toFixed(2)
        const color = b.close >= b.open ? upColor : downColor
        const d = replay.value?.daily[p.dataIndex]
        const posTag = d?.position ? '<span style="color:#2DB757">●持仓</span>' : ''
        const sig = d?.signal_buy ? ' <b style="color:#2DB757">买入信号</b>' : d?.signal_sell ? ' <b style="color:#E84040">卖出信号</b>' : ''
        const ev = replay.value?.events.find((x) => x.index === p.dataIndex)
        const evTag = ev ? (ev.kind === 'entry'
          ? ' <b style="color:#2DB757">▲建仓 @' + ev.price + '</b>'
          : ' <b style="color:#E84040">▼平仓 @' + ev.price + (ev.reason ? ' (' + reasonCn(ev.reason) + ')' : '') + (ev.pnl !== undefined ? ' 盈亏' + (ev.pnl >= 0 ? '+' : '') + ev.pnl : '') + '</b>') : ''
        return `<div style="font-size:12px">
          <div style="margin-bottom:4px;color:${gridText}">${p.axisValue}${posTag}${sig}${evTag}</div>
          <div>开 <b>${b.open}</b> 收 <b style="color:${color}">${b.close}</b></div>
          <div>低 <b>${b.low}</b> 高 <b>${b.high}</b></div>
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
      { type: 'inside', xAxisIndex: [0, 1], start: (start / bars.value.length) * 100, end: ((start + visible) / bars.value.length) * 100 },
    ],
    series: [
      {
        type: 'candlestick',
        xAxisIndex: 0, yAxisIndex: 0,
        data: ohlc,
        itemStyle: { color: upColor, color0: downColor, borderColor: upColor, borderColor0: downColor },
        markArea: { silent: true, data: markAreas },
        markPoint: {
          symbol: 'pin', symbolSize: 26, data: markPoints,
          label: { show: true, color: '#fff', fontSize: 9, fontWeight: 'bold' },
          itemStyle: { borderColor: '#fff', borderWidth: 1 },
        },
      },
      { name: 'MA5', type: 'line', xAxisIndex: 0, yAxisIndex: 0, data: ma(5), smooth: true, symbol: 'none', lineStyle: { width: 1, color: '#E8B84B' } },
      { name: 'MA20', type: 'line', xAxisIndex: 0, yAxisIndex: 0, data: ma(20), smooth: true, symbol: 'none', lineStyle: { width: 1, color: '#C16BE0' } },
      {
        type: 'bar',
        xAxisIndex: 1, yAxisIndex: 1,
        data: volumes.map((v, i) => ({ value: v, itemStyle: { color: colors[i] + '88' } })),
        barMaxWidth: 8,
      },
    ],
  }
}

function reasonCn(r: string): string {
  const m: Record<string, string> = {
    stop_loss: '止损', take_profit: '止盈', trailing_stop: '移动止损',
    time_limit: '时间止损', exit_signal: '策略卖出',
  }
  return m[r] || r
}

function renderChart() {
  if (!chart.value || !bars.value.length) return
  try {
    chart.value.setOption(buildOption(), true)
  } catch (e) {
    // ECharts 实例损坏(如 HMR 后 dispose) → 重建
    console.warn('chart setOption failed, re-init', e)
    chart.value.dispose()
    chart.value = null
    initChart()
  }
}

function initChart() {
  if (!el.value) return
  if (chart.value) { chart.value.dispose(); chart.value = null }
  chart.value = echarts.init(el.value, undefined, { renderer: 'canvas' })
  renderChart()
}

// 播放控制
function togglePlay() {
  if (!bars.value.length) return
  playing.value = !playing.value
  if (playing.value) {
    if (cursor.value >= bars.value.length - 1) cursor.value = 0
    playTimer = setInterval(() => {
      if (cursor.value < bars.value.length - 1) {
        cursor.value++
        renderChart()
      } else {
        stopPlay()
      }
    }, speed.value)
  } else if (playTimer) {
    clearInterval(playTimer)
    playTimer = null
  }
}

function stopPlay() {
  playing.value = false
  if (playTimer) { clearInterval(playTimer); playTimer = null }
}

function stepFwd() { if (cursor.value < bars.value.length - 1) { cursor.value++; renderChart() } }
function stepBack() { if (cursor.value > 0) { cursor.value--; renderChart() } }
function jumpStart() { cursor.value = 0; renderChart() }
function jumpEnd() { cursor.value = bars.value.length - 1; renderChart() }

const cursorBar = computed(() => bars.value[cursor.value])
const cursorDaily = computed(() => replay.value?.daily[cursor.value])
const cursorEvent = computed(() => replay.value?.events.find((e) => e.index === cursor.value))

function fmtPct(v: number) { return (v >= 0 ? '+' : '') + (v * 100).toFixed(2) + '%' }

const metrics = computed(() => replay.value?.metrics)

// 主题响应 + resize
const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(() => chart.value?.resize()) : null
let mo: MutationObserver | null = null

onMounted(() => {
  loadStrategies()
  load()
  if (ro && el.value) ro.observe(el.value)
  mo = new MutationObserver(() => { if (chart.value) renderChart() })
  mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
})

watch(() => bars.value.length, async (len) => {
  if (len > 0) {
    await nextTick()
    if (el.value && !chart.value) {
      initChart()
      if (ro && el.value) ro.observe(el.value)
    }
  }
})

onBeforeUnmount(() => {
  stopPlay()
  ro?.disconnect()
  mo?.disconnect()
  chart.value?.dispose()
})

watch([cursor], () => {
  // cursor 变化由播放/步进函数主动 renderChart; 此处只处理外部跳转
})

watch(strategyId, (v) => {
  if (v && bars.value.length) loadReplay()
})
</script>

<template>
  <div>
    <PageHeader title="策略回放" subtitle="选股 → 定区间 → 选策略 → 逐日播放买卖点，观察每笔交易过程">
      <template #right>
        <div class="hdr-actions">
          <input v-model="code" class="code-input" placeholder="股票代码" @keyup.enter="load" @input="doSearch(code)" />
          <select v-model="days" class="sel" @change="load">
            <option :value="120">120日</option>
            <option :value="250">250日</option>
            <option :value="500">500日</option>
            <option :value="1000">1000日</option>
            <option :value="2000">2000日</option>
          </select>
          <select v-model="strategyId" class="sel wide">
            <option value="">选择策略…</option>
            <optgroup v-if="strategies.some(s => s.kind === 'family')" label="5策略家族">
              <option v-for="s in strategies.filter(x => x.kind === 'family')" :key="s.id" :value="s.id">{{ s.name }}</option>
            </optgroup>
            <optgroup v-if="strategies.some(s => s.kind === 'single')" label="LLM 生成策略">
              <option v-for="s in strategies.filter(x => x.kind === 'single')" :key="s.id" :value="s.id">{{ s.name }}</option>
            </optgroup>
          </select>
          <button class="btn" @click="load" :disabled="loading">加载</button>
        </div>
      </template>
    </PageHeader>

    <!-- 搜索下拉 -->
    <div v-if="searchOpen && (searchResults.length || searchLoading)" class="search-pop">
      <div v-if="searchLoading" class="search-item muted">搜索中…</div>
      <div v-for="s in searchResults" :key="s.code" class="search-item" @click="pickStock(s)">
        <span class="mono">{{ s.code }}</span>
        <span class="nm">{{ s.name }}</span>
        <span class="muted">{{ s.status }}</span>
      </div>
    </div>

    <EmptyState v-if="errorMsg && !bars.length" :message="errorMsg" />

    <template v-if="bars.length">
      <!-- 控制条 -->
      <Card class="mt">
        <div class="ctl">
          <button class="btn" @click="jumpStart" title="跳到起点">⏮</button>
          <button class="btn" @click="stepBack" title="上一根">◀</button>
          <button class="btn primary" @click="togglePlay">{{ playing ? '⏸ 暂停' : '▶ 播放' }}</button>
          <button class="btn" @click="stepFwd" title="下一根">▶</button>
          <button class="btn" @click="jumpEnd" title="跳到终点">⏭</button>
          <select v-model="speed" class="sel">
            <option :value="200">快速</option>
            <option :value="600">正常</option>
            <option :value="1500">慢速</option>
          </select>
          <div class="progress">
            <span class="mono">{{ cursorBar?.date }}</span>
            <span class="muted">第 {{ cursor + 1 }} / {{ bars.length }} 根</span>
            <span v-if="cursorDaily?.position" class="tag hold">● 持仓中</span>
            <span v-else class="tag idle">○ 空仓</span>
            <span v-if="cursorDaily?.signal_buy" class="tag buy">买入信号</span>
            <span v-if="cursorDaily?.signal_sell" class="tag sell">卖出信号</span>
            <span v-if="cursorEvent" class="tag" :class="cursorEvent.kind === 'entry' ? 'buy' : 'sell'">
              {{ cursorEvent.kind === 'entry' ? `▲ 建仓 @${cursorEvent.price}` : `▼ 平仓 @${cursorEvent.price} ${cursorEvent.reason ? '(' + reasonCn(cursorEvent.reason) + ')' : ''}` }}
            </span>
          </div>
        </div>
        <div v-if="cursorBar" class="bar-info muted">
          开 {{ cursorBar.open.toFixed(2) }} · 收 <b :class="cursorBar.close >= cursorBar.open ? 'up' : 'down'">{{ cursorBar.close.toFixed(2) }}</b>
          · 高 {{ cursorBar.high.toFixed(2) }} · 低 {{ cursorBar.low.toFixed(2) }}
          · 涨跌 {{ fmtPct((cursorBar.close - cursorBar.open) / cursorBar.open) }}
        </div>
      </Card>

      <!-- K线图 -->
      <Card class="mt">
        <div ref="el" class="chart"></div>
      </Card>

      <!-- 回放统计 -->
      <div v-if="metrics" class="metric-grid mt">
        <Card>
          <div class="metric-label">总收益</div>
          <div class="metric-val" :class="metrics.total_return >= 0 ? 'up' : 'down'">{{ fmtPct(metrics.total_return) }}</div>
        </Card>
        <Card>
          <div class="metric-label">交易次数</div>
          <div class="metric-val">{{ metrics.num_trades }}</div>
        </Card>
        <Card>
          <div class="metric-label">胜率</div>
          <div class="metric-val">{{ (metrics.win_rate * 100).toFixed(1) }}%</div>
        </Card>
        <Card>
          <div class="metric-label">盈亏比</div>
          <div class="metric-val">{{ metrics.profit_factor }}</div>
        </Card>
        <Card>
          <div class="metric-label">期末权益</div>
          <div class="metric-val">{{ metrics.final_equity.toFixed(0) }}</div>
        </Card>
      </div>

      <!-- 交易明细 -->
      <Card class="mt" v-if="replay?.events.length">
        <h4 class="sec-title">交易明细</h4>
        <table class="tbl">
          <thead>
            <tr><th>建仓日</th><th class="ar">建仓价</th><th>平仓日</th><th class="ar">平仓价</th><th>卖出原因</th><th class="ar">盈亏</th></tr>
          </thead>
          <tbody>
            <tr v-for="(e, i) in replay.events.filter(x => x.kind === 'exit')" :key="i">
              <td class="mono">{{ e.entry_date }}</td>
              <td class="ar num">{{ e.entry_price }}</td>
              <td class="mono">{{ e.date }}</td>
              <td class="ar num">{{ e.price }}</td>
              <td><span class="tag" :class="e.reason === 'exit_signal' ? 'sell' : 'hold'">{{ reasonCn(e.reason || '') }}</span></td>
              <td class="ar num" :class="(e.pnl || 0) >= 0 ? 'up' : 'down'">{{ (e.pnl || 0) >= 0 ? '+' : '' }}{{ e.pnl?.toFixed(0) }}</td>
            </tr>
          </tbody>
        </table>
      </Card>
    </template>
  </div>
</template>

<style scoped>
.hdr-actions { display: flex; gap: var(--sp-2); align-items: center; flex-wrap: wrap; }
.code-input, .sel {
  background: var(--bg); border: 1px solid var(--border); border-radius: var(--radius-sm);
  padding: 6px 10px; color: var(--text); font-size: var(--fs-sm);
  font-family: var(--font-mono);
}
.code-input { width: 100px; }
.sel.wide { max-width: 260px; }
.code-input:focus, .sel:focus { border-color: var(--gold); outline: none; }
.btn {
  background: var(--bg); border: 1px solid var(--border); border-radius: var(--radius-sm);
  padding: 6px 12px; color: var(--text); cursor: pointer; font-size: var(--fs-sm);
}
.btn:hover { border-color: var(--gold); }
.btn.primary { background: var(--gold); color: #1A1D23; border-color: var(--gold); font-weight: 600; }
.btn:disabled { opacity: .5; cursor: not-allowed; }
.search-pop {
  position: absolute; z-index: 50; background: var(--panel); border: 1px solid var(--border);
  border-radius: var(--radius); margin-top: 4px; max-height: 320px; overflow-y: auto;
  min-width: 260px; box-shadow: var(--shadow-lg);
}
.search-item { padding: 8px 12px; cursor: pointer; display: flex; gap: 10px; font-size: var(--fs-sm); }
.search-item:hover { background: var(--bg-hover); }
.search-item .mono { color: var(--gold); font-family: var(--font-mono); }
.search-item .nm { color: var(--text); }
.mt { margin-top: var(--sp-4); }
.ctl { display: flex; gap: var(--sp-2); align-items: center; flex-wrap: wrap; }
.progress { display: flex; gap: var(--sp-3); align-items: center; margin-left: auto; flex-wrap: wrap; font-size: var(--fs-sm); }
.mono { font-family: var(--font-mono); }
.bar-info { margin-top: var(--sp-2); font-size: var(--fs-sm); }
.tag { padding: 2px 8px; border-radius: 10px; font-size: 12px; background: var(--bg-hover); color: var(--text-sub); }
.tag.hold { background: rgba(45,183,87,.15); color: var(--down); }
.tag.idle { background: rgba(138,143,154,.15); }
.tag.buy { background: rgba(45,183,87,.2); color: var(--down); font-weight: 600; }
.tag.sell { background: rgba(232,64,64,.2); color: var(--up); font-weight: 600; }
.chart { width: 100%; height: 520px; min-height: 380px; }
.up { color: var(--up); }
.down { color: var(--down); }
.muted { color: var(--text-faint); }
.metric-grid { display: grid; grid-template-columns: repeat(5, 1fr); gap: var(--sp-3); }
.metric-label { font-size: var(--fs-sm); color: var(--text-sub); }
.metric-val { font-size: 20px; font-weight: 600; color: var(--text); margin-top: 4px; }
.tbl { width: 100%; border-collapse: collapse; font-size: var(--fs-sm); }
.tbl th { padding: 8px var(--sp-3); text-align: left; color: var(--text-sub); border-bottom: 1px solid var(--border); }
.tbl .ar { text-align: right; }
.tbl tr:hover { background: var(--bg-hover); }
.tbl td { padding: 8px var(--sp-3); border-bottom: 1px solid var(--border-soft); color: var(--text); }
.sec-title { margin: 0 0 var(--sp-2); color: var(--text); font-size: var(--fs-md); }
.num { font-family: var(--font-mono); }
@media (max-width: 1100px) { .metric-grid { grid-template-columns: repeat(2, 1fr); } }
</style>
