<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref, watch, nextTick } from 'vue'
import * as echarts from 'echarts/core'
import { CandlestickChart, BarChart, LineChart, CustomChart } from 'echarts/charts'
import {
  TooltipComponent, GridComponent, DataZoomComponent, MarkPointComponent, MarkAreaComponent, MarkLineComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import PageHeader from '@/components/PageHeader.vue'
import Card from '@/components/Card.vue'
import EmptyState from '@/components/EmptyState.vue'
import { searchStock, getReplayStrategies, getReplay } from '@/api'
import type { ReplayStrategy, ReplayResult, StockRef } from '@/api'
import { cssVar } from '@/composables/useEChart'

echarts.use([
  CandlestickChart, BarChart, LineChart, CustomChart,
  TooltipComponent, GridComponent, DataZoomComponent, MarkPointComponent, MarkAreaComponent, MarkLineComponent,
  CanvasRenderer,
])

// ── 数据结构(从 API 本地重建, 支持渐进加载) ──
interface ReplayBar { date: string; open: number; high: number; low: number; close: number; volume: number }
interface ReplayDailyExt {
  i: number; date: string; close: number
  signal_buy: boolean; signal_sell: boolean; position: boolean
  qty: number; entry_price: number; entry_index: number
  cash: number; market_value: number; equity: number
  float_pnl: number; realized_pnl: number; cum_fee: number
}
interface ReplayEventExt {
  index: number; date: string; kind: 'entry' | 'exit'; price: number
  reason?: string; qty?: number; fee?: number
  gross_pnl?: number; net_pnl?: number
  entry_date?: string; entry_price?: number; hold_bars?: number
}

const strategies = ref<ReplayStrategy[]>([])
const code = ref('600036')
const name = ref('')
const strategyId = ref('')
const loading = ref(false)
const errorMsg = ref('')

// 起止日期
const startDate = ref('')
const endDate = ref('')

// 交易环境参数
const initialBalance = ref(100000)
const sizingMode = ref<'percent_of_equity' | 'fixed_capital' | 'fixed_qty'>('percent_of_equity')
const sizingValue = ref(0.95)
const commissionRate = ref(0.0003)
const minCommission = ref(5)
const stampTaxRate = ref(0.0005)
const slippage = ref(0.0)
const paramsOpen = ref(false)

// 搜索
const searchResults = ref<StockRef[]>([])
const searchOpen = ref(false)
let searchTimer: ReturnType<typeof setTimeout> | null = null

// ── 回放数据(渐进式) ──
const allBars = ref<ReplayBar[]>([])
const allDaily = ref<ReplayDailyExt[]>([])
const allEvents = ref<ReplayEventExt[]>([])
const allSpans = ref<number[][]>([])
const metrics = ref<ReplayResult['metrics'] | null>(null)

// 渐进窗口: 显示 [windowStart, cursor] 的K线, cursor 前保留至少 KEEP_BACK 根
const KEEP_BACK = 50
const PRELOAD = 25
const cursor = ref(0)

// 播放
const playing = ref(false)
const speed = ref(1) // 1 = 600ms/bar
const SPEED_MS: Record<number, number> = { 0.25: 2400, 0.5: 1200, 1: 600, 2: 300, 4: 150, 8: 75 }
let playTimer: ReturnType<typeof setInterval> | null = null

// 图表
const el = ref<HTMLDivElement>()
const chart = ref<echarts.ECharts | null>(null)
const isDark = computed(() => document.documentElement.getAttribute('data-theme') !== 'ivory')

// 窗口内可见的数据
const visibleBars = computed(() => {
  const start = Math.max(0, cursor.value - KEEP_BACK)
  return allBars.value.slice(0, cursor.value + 1).slice(start)
})
const visibleStart = computed(() => Math.max(0, cursor.value - KEEP_BACK))

function visibleDailyAt(idx: number): ReplayDailyExt | undefined {
  const abs = visibleStart.value + idx
  return allDaily.value[abs]
}

// 当前状态
const cursorBar = computed(() => allBars.value[cursor.value])
const cursorDaily = computed(() => allDaily.value[cursor.value])
const cursorEvent = computed(() => allEvents.value.find((e) => e.index === cursor.value))

// 持仓(当前位置)
const holdingState = computed(() => {
  const d = cursorDaily.value
  if (!d || !d.position) return null
  const bars = (cursor.value - (d.entry_index >= 0 ? d.entry_index : 0)) + 1
  return { ...d, hold_bars: bars }
})

// ── 加载 ──
async function loadStrategies() {
  try { strategies.value = await getReplayStrategies() } catch { strategies.value = [] }
}

function buildQuery() {
  return {
    code: code.value,
    strategy: strategyId.value,
    days: 2500,
    start: startDate.value || '',
    end: endDate.value || '',
    initial_balance: initialBalance.value,
    sizing_mode: sizingMode.value,
    sizing_value: sizingValue.value,
    commission_rate: commissionRate.value,
    min_commission: minCommission.value,
    stamp_tax_rate: stampTaxRate.value,
    slippage: slippage.value,
  }
}

async function load() {
  if (!code.value || !strategyId.value) return
  loading.value = true
  errorMsg.value = ''
  stopPlay()
  try {
    const r = await getReplay(
      code.value, strategyId.value, 2500,
      buildQuery(),
    )
    allBars.value = r.bars
    allDaily.value = r.daily
    allEvents.value = r.events
    allSpans.value = r.holding_spans
    metrics.value = r.metrics
    cursor.value = 0
    await nextTick()
    initChart()
  } catch (e) {
    errorMsg.value = e instanceof Error ? e.message : '加载失败'
    allBars.value = []
    allDaily.value = []
  } finally {
    loading.value = false
  }
}

async function loadKlineOnly() {
  // 选股后仅加载(策略未选时也可预览K线)
  if (!code.value) return
  loading.value = true
  errorMsg.value = ''
  try {
    if (strategyId.value) { await load(); return }
    // 无策略时只显示K线: 直接调 replay 但策略不选会报错, 改为提示
    errorMsg.value = ''
  } finally { loading.value = false }
}

function doSearch(q: string) {
  if (searchTimer) clearTimeout(searchTimer)
  if (!q.trim()) { searchResults.value = []; return }
  searchTimer = setTimeout(async () => {
    try { searchResults.value = await searchStock(q.trim()) }
    catch { searchResults.value = [] }
  }, 250)
}

function pickStock(s: StockRef) {
  code.value = s.code
  name.value = s.name
  searchOpen.value = false
  searchResults.value = []
  if (strategyId.value) load()
}

// ── 图表 ──
function buildOption(): echarts.EChartsCoreOption {
  const upColor = cssVar('--up', '#E84040')
  const downColor = cssVar('--down', '#2DB757')
  const gridText = isDark.value ? '#8A8F9A' : '#666'
  const gridLine = isDark.value ? '#2A2D35' : '#E5E7EB'

  const bars = visibleBars.value
  const dates = bars.map((b) => b.date)
  const ohlc = bars.map((b) => [b.open, b.close, b.low, b.high])
  const volumes = bars.map((b) => b.volume)
  const colors = bars.map((b) => (b.close >= b.open ? upColor : downColor))
  const vStart = visibleStart.value

  const ma = (n: number) =>
    bars.map((_, i) => {
      if (i < n - 1) return null
      let sum = 0
      for (let j = i - n + 1; j <= i; j++) sum += bars[j].close
      return +(sum / n).toFixed(2)
    })

  // 买卖点(窗口内)
  const markPoints: { coord: [number, number]; value: string; symbol: string; symbolSize: number; itemStyle: { color: string } }[] = []
  const markAreas: Array<Array<{ xAxis: number; itemStyle?: { color: string } }>> = []

  for (const e of allEvents.value) {
    const local = e.index - vStart
    if (local < 0 || local >= bars.length) continue
    if (e.kind === 'entry') {
      markPoints.push({ coord: [local, e.price], value: 'B', symbol: 'pin', symbolSize: 24, itemStyle: { color: '#2DB757' } })
    } else {
      markPoints.push({ coord: [local, e.price], value: 'S', symbol: 'pin', symbolSize: 24, itemStyle: { color: '#E84040' } })
    }
  }
  for (const [s, e] of allSpans.value) {
    const ls = s - vStart
    const le = Math.min(e, cursor.value) - vStart
    if (le < 0 || ls >= bars.length) continue
    markAreas.push([
      { xAxis: Math.max(0, ls), itemStyle: { color: 'rgba(45,183,87,0.13)' } },
      { xAxis: Math.min(bars.length - 1, le) },
    ])
  }

  // 当前播放位置竖线
  const curLocal = cursor.value - vStart
  const markLines = curLocal >= 0 && curLocal < bars.length
    ? [{ xAxis: curLocal, lineStyle: { color: '#D4A574', type: 'dashed' as const, width: 1 } }]
    : []

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
        const b = bars[p.dataIndex]
        if (!b) return ''
        const chg = ((b.close - b.open) / b.open * 100).toFixed(2)
        const color = b.close >= b.open ? upColor : downColor
        const d = visibleDailyAt(p.dataIndex)
        const posTag = d?.position ? '<span style="color:#2DB757">●持仓</span>' : ''
        const sig = d?.signal_buy ? ' <b style="color:#2DB757">买入信号</b>' : d?.signal_sell ? ' <b style="color:#E84040">卖出信号</b>' : ''
        const ev = allEvents.value.find((x) => x.index === vStart + p.dataIndex)
        const evTag = ev ? (ev.kind === 'entry'
          ? ' <b style="color:#2DB757">▲建仓 @' + ev.price + (ev.qty ? ' ×' + ev.qty + '股' : '') + '</b>'
          : ' <b style="color:#E84040">▼平仓 @' + ev.price + (ev.reason ? ' (' + reasonCn(ev.reason) + ')' : '') + (ev.net_pnl !== undefined ? ' 净盈亏' + (ev.net_pnl >= 0 ? '+' : '') + ev.net_pnl : '') + '</b>') : ''
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
      { left: 60, right: 20, top: 20, height: '52%' },
      { left: 60, right: 20, top: '70%', height: '12%' },
      { left: 60, right: 20, top: '85%', height: '8%' },
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
        axisLabel: { show: false },
        splitLine: { show: false },
      },
      {
        type: 'category', data: dates, gridIndex: 2,
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
        splitNumber: 2, axisLabel: { show: false }, splitLine: { show: false },
      },
      {
        type: 'value', gridIndex: 2, scale: true,
        splitNumber: 2, axisLabel: { show: false }, splitLine: { show: false },
      },
    ],
    series: [
      {
        type: 'candlestick',
        xAxisIndex: 0, yAxisIndex: 0,
        data: ohlc,
        itemStyle: { color: upColor, color0: downColor, borderColor: upColor, borderColor0: downColor },
        markArea: { silent: true, data: markAreas },
        markPoint: {
          symbol: 'pin', symbolSize: 24, data: markPoints,
          label: { show: true, color: '#fff', fontSize: 9, fontWeight: 'bold' },
          itemStyle: { borderColor: '#fff', borderWidth: 1 },
        },
        markLine: { silent: true, symbol: 'none', data: markLines },
      },
      { name: 'MA5', type: 'line', xAxisIndex: 0, yAxisIndex: 0, data: ma(5), smooth: true, symbol: 'none', lineStyle: { width: 1, color: '#E8B84B' } },
      { name: 'MA20', type: 'line', xAxisIndex: 0, yAxisIndex: 0, data: ma(20), smooth: true, symbol: 'none', lineStyle: { width: 1, color: '#C16BE0' } },
      {
        type: 'bar',
        xAxisIndex: 1, yAxisIndex: 1,
        data: volumes.map((v, i) => ({ value: v, itemStyle: { color: colors[i] + '88' } })),
        barMaxWidth: 8,
      },
      {
        // 权益曲线(第三行)
        name: '权益',
        type: 'line',
        xAxisIndex: 2, yAxisIndex: 2,
        data: bars.map((_, i) => visibleDailyAt(i)?.equity ?? null),
        symbol: 'none',
        lineStyle: { width: 1.2, color: '#5B8FF9' },
        areaStyle: { color: 'rgba(91,143,249,0.12)' },
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
  if (!chart.value || !visibleBars.value.length) return
  try {
    chart.value.setOption(buildOption(), true)
  } catch (e) {
    console.warn('chart setOption failed, re-init', e)
    chart.value?.dispose()
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

// ── 播放控制 ──
function setSpeed(sp: number) { speed.value = sp }

function togglePlay() {
  if (!allBars.value.length) return
  playing.value = !playing.value
  if (playing.value) {
    if (cursor.value >= allBars.value.length - 1) cursor.value = 0
    playTimer = setInterval(() => {
      if (cursor.value < allBars.value.length - 1) {
        cursor.value++
        renderChart()
      } else {
        stopPlay()
      }
    }, SPEED_MS[speed.value] ?? 600)
  } else if (playTimer) {
    clearInterval(playTimer)
    playTimer = null
  }
}

function stopPlay() {
  playing.value = false
  if (playTimer) { clearInterval(playTimer); playTimer = null }
}

function stepFwd() { if (cursor.value < allBars.value.length - 1) { cursor.value++; renderChart() } }
function stepBack() { if (cursor.value > 0) { cursor.value--; renderChart() } }
function jumpStart() { cursor.value = 0; renderChart() }
function jumpEnd() { cursor.value = allBars.value.length - 1; renderChart() }

// 滚动条(手动拖动)
function onSliderInput(ev: Event) {
  const v = Number((ev.target as HTMLInputElement).value)
  cursor.value = v
  renderChart()
}

// 买入方式切换时重置为合理默认值
watch(sizingMode, (m) => {
  if (m === 'percent_of_equity') sizingValue.value = 0.95
  else if (m === 'fixed_capital') sizingValue.value = 50000
  else sizingValue.value = 1000
})

// 速度变化时若在播放, 重启计时器
watch(speed, () => {
  if (playing.value) {
    if (playTimer) clearInterval(playTimer)
    playTimer = setInterval(() => {
      if (cursor.value < allBars.value.length - 1) {
        cursor.value++
        renderChart()
      } else {
        stopPlay()
      }
    }, SPEED_MS[speed.value] ?? 600)
  }
})

watch(cursor, () => { renderChart() })

function fmtPct(v: number) { return (v >= 0 ? '+' : '') + (v * 100).toFixed(2) + '%' }
function fmtMoney(v: number) { return v.toLocaleString('zh-CN', { maximumFractionDigits: 0 }) }

// 主题响应 + resize
const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(() => chart.value?.resize()) : null
let mo: MutationObserver | null = null

onMounted(() => {
  loadStrategies()
  if (ro && el.value) ro.observe(el.value)
  mo = new MutationObserver(() => { if (chart.value) renderChart() })
  mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
})

onBeforeUnmount(() => {
  stopPlay()
  ro?.disconnect()
  mo?.disconnect()
  chart.value?.dispose()
})

watch(() => allBars.value.length, async (len) => {
  if (len > 0) {
    await nextTick()
    if (el.value && !chart.value) {
      initChart()
      if (ro && el.value) ro.observe(el.value)
    }
  }
})

watch(strategyId, (v) => {
  if (v && code.value) load()
})
</script>

<template>
  <div>
    <PageHeader title="策略回放" subtitle="真实交易环境模拟 — 逐日播放买卖点 / 持仓盈亏 / 账户权益">
      <template #right>
        <div class="hdr-actions">
          <input v-model="code" class="code-input" placeholder="股票代码" @keyup.enter="pickStock({ code: code, name: '', status: '' } as StockRef)" @input="doSearch(code)" />
          <select v-model="strategyId" class="sel wide">
            <option value="">选择策略…</option>
            <optgroup v-if="strategies.some(s => s.kind === 'family')" label="5策略家族">
              <option v-for="s in strategies.filter(x => x.kind === 'family')" :key="s.id" :value="s.id">{{ s.name }}</option>
            </optgroup>
            <optgroup v-if="strategies.some(s => s.kind === 'single')" label="LLM 生成策略">
              <option v-for="s in strategies.filter(x => x.kind === 'single')" :key="s.id" :value="s.id">{{ s.name }}</option>
            </optgroup>
          </select>
          <button class="btn primary" @click="load" :disabled="loading || !strategyId">{{ loading ? '加载中…' : '开始回放' }}</button>
        </div>
      </template>
    </PageHeader>

    <!-- 搜索下拉 -->
    <div v-if="searchOpen && searchResults.length" class="search-pop">
      <div v-for="s in searchResults" :key="s.code" class="search-item" @click="pickStock(s)">
        <span class="mono">{{ s.code }}</span>
        <span class="nm">{{ s.name }}</span>
        <span class="muted">{{ s.status }}</span>
      </div>
    </div>

    <!-- 参数面板 -->
    <Card class="mt">
      <div class="param-bar">
        <div class="param-item">
          <label>起始日期</label>
          <input v-model="startDate" type="date" class="date-input" />
        </div>
        <div class="param-item">
          <label>结束日期</label>
          <input v-model="endDate" type="date" class="date-input" />
        </div>
        <button class="btn" @click="paramsOpen = !paramsOpen">{{ paramsOpen ? '收起参数 ▲' : '交易环境参数 ▼' }}</button>
        <div v-if="!startDate && !endDate" class="muted note">默认最近约500根K线; 设日期后从起点前150根预热因子</div>
      </div>

      <div v-if="paramsOpen" class="params-grid">
        <div class="param-item">
          <label>账户总金额(元)</label>
          <input v-model.number="initialBalance" type="number" min="10000" step="10000" class="num-input" />
        </div>
        <div class="param-item">
          <label>买入方式</label>
          <select v-model="sizingMode" class="sel">
            <option value="percent_of_equity">总资产百分比</option>
            <option value="fixed_capital">固定金额</option>
            <option value="fixed_qty">固定股数</option>
          </select>
        </div>
        <div class="param-item">
          <label>{{ sizingMode === 'fixed_qty' ? '股数(股)' : sizingMode === 'fixed_capital' ? '金额(元)' : '仓位比例(0~1)' }}</label>
          <input v-model.number="sizingValue" type="number" :min="sizingMode === 'percent_of_equity' ? 0.01 : 100" :step="sizingMode === 'percent_of_equity' ? 0.05 : sizingMode === 'fixed_qty' ? 100 : 10000" class="num-input" />
        </div>
        <div class="param-item">
          <label>佣金率</label>
          <input v-model.number="commissionRate" type="number" min="0" step="0.0001" class="num-input" />
        </div>
        <div class="param-item">
          <label>最低佣金(元)</label>
          <input v-model.number="minCommission" type="number" min="0" step="1" class="num-input" />
        </div>
        <div class="param-item">
          <label>印花税率(卖出)</label>
          <input v-model.number="stampTaxRate" type="number" min="0" step="0.0001" class="num-input" />
        </div>
        <div class="param-item">
          <label>滑点</label>
          <input v-model.number="slippage" type="number" min="0" step="0.001" class="num-input" />
        </div>
        <div class="param-item wide">
          <button class="btn primary" @click="load" :disabled="loading || !strategyId">应用参数并重新回放</button>
        </div>
      </div>
    </Card>

    <EmptyState v-if="errorMsg && !allBars.length" :message="errorMsg" />

    <template v-if="allBars.length">
      <!-- 播放控制 -->
      <Card class="mt">
        <div class="ctl">
          <button class="btn" @click="stepBack" title="上一根">◀</button>
          <button class="btn primary wide-btn" @click="togglePlay">{{ playing ? '⏸ 暂停' : '▶ 播放' }}</button>
          <button class="btn" @click="stepFwd" title="下一根">▶</button>
          <span class="ctl-sep"></span>
          <span class="lbl">速度</span>
          <div class="speed-btns">
            <button v-for="s in [0.25, 0.5, 1, 2, 4, 8]" :key="s" class="btn speed-btn" :class="{ active: speed === s }" @click="setSpeed(s)">{{ s }}x</button>
          </div>
          <span class="ctl-sep"></span>
          <input type="range" class="slider" :min="0" :max="allBars.length - 1" :value="cursor" @input="onSliderInput" />
          <span class="mono pos">{{ cursor + 1 }}/{{ allBars.length }}</span>
        </div>
        <div class="status-line">
          <span class="mono">{{ cursorBar?.date }}</span>
          <span v-if="cursorDaily?.position" class="tag hold">● 持仓中 {{ cursorDaily?.qty }}股</span>
          <span v-else class="tag idle">○ 空仓</span>
          <span v-if="cursorDaily?.signal_buy" class="tag buy">买入信号</span>
          <span v-if="cursorDaily?.signal_sell" class="tag sell">卖出信号</span>
          <span v-if="cursorEvent" class="tag" :class="cursorEvent.kind === 'entry' ? 'buy' : 'sell'">
            {{ cursorEvent.kind === 'entry' ? `▲ 建仓 @${cursorEvent.price} ×${cursorEvent.qty}股` : `▼ 平仓 @${cursorEvent.price} ${cursorEvent.reason ? '(' + reasonCn(cursorEvent.reason) + ')' : ''} ${cursorEvent.net_pnl !== undefined ? '净盈亏 ' + (cursorEvent.net_pnl >= 0 ? '+' : '') + cursorEvent.net_pnl : ''}` }}
          </span>
        </div>
      </Card>

      <!-- K线图 -->
      <Card class="mt">
        <div ref="el" class="chart"></div>
      </Card>

      <!-- 账户面板 + 指标 -->
      <div class="acct-grid mt">
        <Card>
          <div class="metric-label">总资产(权益)</div>
          <div class="metric-val mono">{{ cursorDaily ? fmtMoney(cursorDaily.equity) : '—' }}</div>
          <div class="metric-sub muted">期初 {{ metrics ? fmtMoney(metrics.initial_balance) : '—' }}</div>
        </Card>
        <Card>
          <div class="metric-label">现金</div>
          <div class="metric-val mono">{{ cursorDaily ? fmtMoney(cursorDaily.cash) : '—' }}</div>
        </Card>
        <Card>
          <div class="metric-label">持仓市值</div>
          <div class="metric-val mono">{{ cursorDaily ? fmtMoney(cursorDaily.market_value) : '—' }}</div>
          <div class="metric-sub muted">{{ holdingState ? `成本 ${holdingState.entry_price} · 持有${holdingState.hold_bars}根` : '无持仓' }}</div>
        </Card>
        <Card>
          <div class="metric-label">浮动盈亏</div>
          <div class="metric-val mono" :class="(cursorDaily?.float_pnl ?? 0) >= 0 ? 'up' : 'down'">
            {{ cursorDaily ? (cursorDaily.float_pnl >= 0 ? '+' : '') + fmtMoney(cursorDaily.float_pnl) : '—' }}
          </div>
        </Card>
        <Card>
          <div class="metric-label">已实现盈亏</div>
          <div class="metric-val mono" :class="(cursorDaily?.realized_pnl ?? 0) >= 0 ? 'up' : 'down'">
            {{ cursorDaily ? (cursorDaily.realized_pnl >= 0 ? '+' : '') + fmtMoney(cursorDaily.realized_pnl) : '—' }}
          </div>
        </Card>
        <Card>
          <div class="metric-label">累计费用</div>
          <div class="metric-val mono muted">{{ cursorDaily ? fmtMoney(cursorDaily.cum_fee) : '—' }}</div>
        </Card>
      </div>

      <!-- 最终指标 -->
      <div v-if="metrics" class="metric-grid mt">
        <Card>
          <div class="metric-label">区间总收益</div>
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
          <div class="metric-label">最大回撤</div>
          <div class="metric-val down">{{ (metrics.max_drawdown * 100).toFixed(1) }}%</div>
        </Card>
        <Card>
          <div class="metric-label">期末权益</div>
          <div class="metric-val">{{ fmtMoney(metrics.final_equity) }}</div>
        </Card>
      </div>

      <!-- 交易明细 -->
      <Card class="mt" v-if="allEvents.filter(e => e.kind === 'exit').length">
        <h4 class="sec-title">交易明细（真实费用模拟）</h4>
        <table class="tbl">
          <thead>
            <tr>
              <th>建仓日</th><th class="ar">建仓价</th><th>平仓日</th><th class="ar">平仓价</th>
              <th class="ar">持有</th><th>卖出原因</th><th class="ar">毛盈亏</th><th class="ar">费用</th><th class="ar">净盈亏</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(e, i) in allEvents.filter(x => x.kind === 'exit')" :key="i">
              <td class="mono">{{ e.entry_date }}</td>
              <td class="ar num">{{ e.entry_price }}</td>
              <td class="mono">{{ e.date }}</td>
              <td class="ar num">{{ e.price }}</td>
              <td class="ar num muted">{{ e.hold_bars }}根</td>
              <td><span class="tag" :class="e.reason === 'exit_signal' ? 'sell' : 'hold'">{{ reasonCn(e.reason || '') }}</span></td>
              <td class="ar num" :class="(e.gross_pnl || 0) >= 0 ? 'up' : 'down'">{{ (e.gross_pnl || 0) >= 0 ? '+' : '' }}{{ e.gross_pnl?.toFixed(0) }}</td>
              <td class="ar num muted">{{ e.fee?.toFixed(2) }}</td>
              <td class="ar num bold" :class="(e.net_pnl || 0) >= 0 ? 'up' : 'down'">{{ (e.net_pnl || 0) >= 0 ? '+' : '' }}{{ e.net_pnl?.toFixed(0) }}</td>
            </tr>
          </tbody>
        </table>
      </Card>
    </template>

    <EmptyState v-if="!allBars.length && !errorMsg && strategyId" message="选择股票和策略后点击「开始回放」" />
  </div>
</template>

<style scoped>
.hdr-actions { display: flex; gap: var(--sp-2); align-items: center; flex-wrap: wrap; }
.code-input, .sel, .date-input, .num-input {
  background: var(--bg); border: 1px solid var(--border); border-radius: var(--radius-sm);
  padding: 6px 10px; color: var(--text); font-size: var(--fs-sm);
  font-family: var(--font-mono);
}
.code-input { width: 100px; }
.sel.wide { max-width: 280px; }
.date-input { width: 150px; }
.num-input { width: 110px; }
.code-input:focus, .sel:focus, .date-input:focus, .num-input:focus { border-color: var(--gold); outline: none; }
.btn {
  background: var(--bg); border: 1px solid var(--border); border-radius: var(--radius-sm);
  padding: 6px 12px; color: var(--text); cursor: pointer; font-size: var(--fs-sm);
}
.btn:hover { border-color: var(--gold); }
.btn.primary { background: var(--gold); color: #1A1D23; border-color: var(--gold); font-weight: 600; }
.btn:disabled { opacity: .5; cursor: not-allowed; }
.wide-btn { min-width: 110px; }
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
.param-bar { display: flex; gap: var(--sp-3); align-items: center; flex-wrap: wrap; }
.param-item { display: flex; flex-direction: column; gap: 4px; }
.param-item label { font-size: 12px; color: var(--text-sub); }
.param-item.wide { justify-content: flex-end; }
.note { font-size: 12px; }
.params-grid { display: flex; gap: var(--sp-3); flex-wrap: wrap; margin-top: var(--sp-3); padding-top: var(--sp-3); border-top: 1px solid var(--border-soft); }
.ctl { display: flex; gap: var(--sp-2); align-items: center; flex-wrap: wrap; }
.ctl-sep { width: 1px; height: 22px; background: var(--border); margin: 0 var(--sp-1); }
.lbl { font-size: var(--fs-sm); color: var(--text-sub); }
.speed-btns { display: flex; gap: 4px; }
.speed-btn { padding: 4px 10px; }
.speed-btn.active { background: var(--gold); color: #1A1D23; border-color: var(--gold); font-weight: 600; }
.slider { flex: 1; min-width: 140px; accent-color: var(--gold); }
.pos { font-size: var(--fs-sm); color: var(--text-sub); white-space: nowrap; }
.status-line { display: flex; gap: var(--sp-3); align-items: center; margin-top: var(--sp-2); flex-wrap: wrap; font-size: var(--fs-sm); }
.mono { font-family: var(--font-mono); }
.tag { padding: 2px 8px; border-radius: 10px; font-size: 12px; background: var(--bg-hover); color: var(--text-sub); }
.tag.hold { background: rgba(45,183,87,.15); color: var(--down); }
.tag.idle { background: rgba(138,143,154,.15); }
.tag.buy { background: rgba(45,183,87,.2); color: var(--down); font-weight: 600; }
.tag.sell { background: rgba(232,64,64,.2); color: var(--up); font-weight: 600; }
.chart { width: 100%; height: 560px; min-height: 400px; }
.acct-grid { display: grid; grid-template-columns: repeat(6, 1fr); gap: var(--sp-3); }
.metric-grid { display: grid; grid-template-columns: repeat(6, 1fr); gap: var(--sp-3); }
.metric-label { font-size: var(--fs-sm); color: var(--text-sub); }
.metric-val { font-size: 20px; font-weight: 600; color: var(--text); margin-top: 4px; }
.metric-sub { font-size: 12px; margin-top: 2px; }
.up { color: var(--up); }
.down { color: var(--down); }
.muted { color: var(--text-faint); }
.tbl { width: 100%; border-collapse: collapse; font-size: var(--fs-sm); }
.tbl th { padding: 8px var(--sp-3); text-align: left; color: var(--text-sub); border-bottom: 1px solid var(--border); }
.tbl .ar { text-align: right; }
.tbl tr:hover { background: var(--bg-hover); }
.tbl td { padding: 8px var(--sp-3); border-bottom: 1px solid var(--border-soft); color: var(--text); }
.sec-title { margin: 0 0 var(--sp-2); color: var(--text); font-size: var(--fs-md); }
.num { font-family: var(--font-mono); }
.bold { font-weight: 600; }
@media (max-width: 1400px) { .acct-grid, .metric-grid { grid-template-columns: repeat(3, 1fr); } }
</style>
