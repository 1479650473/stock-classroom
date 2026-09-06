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

// ── 数据结构 ──
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

// ── 回合状态机: setup(准备, 可调设置) → trading(回合中, 设置锁定) → settled(期末结算) ──
const phase = ref<'setup' | 'trading' | 'settled'>('setup')

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
const settingsOpen = ref(true)

// 搜索
const searchResults = ref<StockRef[]>([])
const searchOpen = ref(false)
let searchTimer: ReturnType<typeof setTimeout> | null = null

// ── 回放数据 ──
const allBars = ref<ReplayBar[]>([])
const allDaily = ref<ReplayDailyExt[]>([])
const allEvents = ref<ReplayEventExt[]>([])
const allSpans = ref<number[][]>([])
const metrics = ref<ReplayResult['metrics'] | null>(null)

// ── 播放指针(全局索引, 0-based) ──
const cursor = ref(0)

// 窗口参数: 固定显示 WINDOW_SIZE 根, 窗口左端随 cursor 移动
const WINDOW_SIZE = 70
const KEEP_BACK = 50   // cursor 左侧保留历史根数(窗口后 50 历史 + 20 未来预览)

// 渲染窗口(显式计算, 不依赖全局 computed 联动避免时序歧义)
function getWindow(): { start: number; end: number } {
  const len = allBars.value.length
  if (!len) return { start: 0, end: 0 }
  const cur = Math.min(cursor.value, len - 1)
  // cursor 在窗口 60% 处, 后面留 40% 未来预览; 窗口右端至少到 cursor
  const idealStart = cur - KEEP_BACK
  const start = Math.max(0, idealStart)
  // 保证窗口至少 WINDOW_SIZE 根(开头向后借, 结尾向前截)
  const end = Math.min(len - 1, Math.max(cur, start + WINDOW_SIZE - 1))
  return { start, end }
}

// 播放
const playing = ref(false)
const speed = ref(1)
const SPEED_MS: Record<number, number> = { 0.25: 2400, 0.5: 1200, 1: 600, 2: 300, 4: 150, 8: 75 }

// 侧栏(交易明细)
const sideOpen = ref(true)

// 图表
const el = ref<HTMLDivElement>()
const chart = ref<echarts.ECharts | null>(null)
const isDark = computed(() => document.documentElement.getAttribute('data-theme') !== 'ivory')

// ── 当前状态(供面板/状态栏) ──
const cursorBar = computed(() => allBars.value[cursor.value])
const cursorDaily = computed(() => allDaily.value[cursor.value])
const cursorEvent = computed(() => allEvents.value.find((e) => e.index === cursor.value))

const holdingState = computed(() => {
  const d = cursorDaily.value
  if (!d || !d.position) return null
  const bars = (cursor.value - (d.entry_index >= 0 ? d.entry_index : 0)) + 1
  return { ...d, hold_bars: bars }
})

// 设置摘要(折叠时显示)
const settingsSummary = computed(() => {
  const parts: string[] = []
  parts.push(startDate.value || endDate.value
    ? `${startDate.value || '起点'} ~ ${endDate.value || '终点'}`
    : '默认近500根')
  parts.push(`${(initialBalance.value / 10000).toFixed(0)}万`)
  if (sizingMode.value === 'percent_of_equity') parts.push(`仓位${(sizingValue.value * 100).toFixed(0)}%`)
  else if (sizingMode.value === 'fixed_capital') parts.push(`固定${(sizingValue.value / 10000).toFixed(1)}万/笔`)
  else parts.push(`固定${sizingValue.value}股/笔`)
  parts.push(`佣金万${(commissionRate.value * 10000).toFixed(0)}`)
  return parts.join(' · ')
})

// 回合进度
const roundProgress = computed(() =>
  allBars.value.length ? Math.round((cursor.value / (allBars.value.length - 1)) * 100) : 0)

// 当前策略名(结算弹窗用)
const strategyName = computed(() =>
  strategies.value.find((x) => x.id === strategyId.value)?.name || '')

// 退出交易(按平仓时间倒序, 侧栏时间线)
const exitEvents = computed(() =>
  allEvents.value.filter((e) => e.kind === 'exit').slice().reverse())

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
  phase.value = 'setup'
  try {
    const r = await getReplay(code.value, strategyId.value, 2500, buildQuery())
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

function doSearch(q: string) {
  if (searchTimer) clearTimeout(searchTimer)
  if (!q.trim()) { searchResults.value = []; searchOpen.value = false; return }
  searchTimer = setTimeout(async () => {
    try {
      searchResults.value = await searchStock(q.trim())
      searchOpen.value = searchResults.value.length > 0
    } catch { searchResults.value = [] }
  }, 250)
}

function pickStock(s: StockRef) {
  code.value = s.code
  name.value = s.name
  searchOpen.value = false
  searchResults.value = []
  if (strategyId.value) load()
}

// ── 回合控制 ──
function startRound() {
  if (phase.value === 'setup') phase.value = 'trading'
}

function newRound() {
  stopPlay()
  cursor.value = 0
  phase.value = 'setup'
  settingsOpen.value = true
  render()
}

// ═══════════════════════════════════════════════════════════
//  图表渲染 — 单一渲染管线: render() 依据当前 cursor 计算窗口后全量重绘
//  每次 cursor 变化只会触发一次 render(经 rAF 合并), 图表与数据严格同步
// ═══════════════════════════════════════════════════════════
function buildOption(): echarts.EChartsCoreOption {
  const upColor = cssVar('--up', '#E84040')
  const downColor = cssVar('--down', '#2DB757')
  const gridText = isDark.value ? '#8A8F9A' : '#666'
  const gridLine = isDark.value ? '#2A2D35' : '#E5E7EB'

  const { start, end } = getWindow()
  const bars = allBars.value.slice(start, end + 1)
  const total = bars.length
  if (!total) return {}
  const dates = bars.map((b) => b.date)
  const ohlc = bars.map((b) => [b.open, b.close, b.low, b.high])
  const volumes = bars.map((b) => b.volume)
  const colors = bars.map((b) => (b.close >= b.open ? upColor : downColor))
  const curLocal = cursor.value - start

  const ma = (n: number) =>
    bars.map((_, i) => {
      if (i < n - 1) return null
      let sum = 0
      for (let j = i - n + 1; j <= i; j++) sum += bars[j].close
      return +(sum / n).toFixed(2)
    })

  // 买卖点(仅显示到当前 cursor 为止的事件, 但保留全部标记便于观察)
  const markPoints: { coord: [number, number]; value: string; symbol: string; symbolSize: number; itemStyle: { color: string } }[] = []
  for (const e of allEvents.value) {
    if (e.index < start || e.index > end) continue
    const local = e.index - start
    if (e.kind === 'entry') {
      markPoints.push({ coord: [local, e.price], value: 'B', symbol: 'pin', symbolSize: 24, itemStyle: { color: '#2DB757' } })
    } else {
      markPoints.push({ coord: [local, e.price], value: 'S', symbol: 'pin', symbolSize: 24, itemStyle: { color: '#E84040' } })
    }
  }

  // 持仓区间(裁剪到当前窗口; 仅显示已经发生的持仓段, 即 exit <= cursor 或 正在持仓中)
  const markAreas: Array<Array<{ xAxis: number; itemStyle?: { color: string } }>> = []
  for (const [s, e] of allSpans.value) {
    const visibleEnd = Math.min(e, cursor.value)   // 只显示已"发生"的持仓
    if (visibleEnd < start || s > end) continue
    const ls = Math.max(s, start)
    const le = Math.min(visibleEnd, end)
    if (le < ls) continue
    markAreas.push([
      { xAxis: ls - start, itemStyle: { color: 'rgba(45,183,87,0.13)' } },
      { xAxis: le - start },
    ])
  }

  // 播放头竖线(独立 markLine)
  const markLines = [
    { xAxis: curLocal, lineStyle: { color: '#D4A574', type: 'dashed' as const, width: 1 } },
  ]

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
        const absIdx = start + p.dataIndex
        const d = allDaily.value[absIdx]
        const posTag = d?.position ? '<span style="color:#2DB757">●持仓</span>' : ''
        const sig = d?.signal_buy ? ' <b style="color:#2DB757">买入信号</b>' : d?.signal_sell ? ' <b style="color:#E84040">卖出信号</b>' : ''
        const ev = allEvents.value.find((x) => x.index === absIdx)
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
        id: 'candlestick',
        type: 'candlestick',
        xAxisIndex: 0, yAxisIndex: 0,
        data: ohlc,
        barMaxWidth: 11,
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
        name: '权益',
        type: 'line',
        xAxisIndex: 2, yAxisIndex: 2,
        data: bars.map((_, i) => allDaily.value[start + i]?.equity ?? null),
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

// 渲染入口: 同步渲染(scheduleStep/单步/拖动/窗口变化直接渲染, 不依赖 rAF —— rAF 在隐藏页会挂起,
// 且渲染量小(<70根K线 ~30ms), 600ms一拍完全可承受)
function render() {
  doRender()
}

function doRender() {
  if (!chart.value || !allBars.value.length) return
  try {
    chart.value.setOption(buildOption(), true)
  } catch (e) {
    console.warn('chart setOption failed, re-init', e)
    try { chart.value?.dispose() } catch { /* ignore */ }
    chart.value = null
    try { initChart() } catch (e2) { console.warn('chart re-init failed', e2) }
  }
}

function initChart() {
  if (!el.value) return
  if (chart.value) { chart.value.dispose(); chart.value = null }
  chart.value = echarts.init(el.value, undefined, { renderer: 'canvas' })
  doRender()
}

// ═══════════════════════════════════════════════════════════
//  播放控制 — 一根一根: 每拍【推进1根 + 渲染】, 渲染完成后调度下一拍
//  不使用自转时间轴(rAF/interval), 保证渲染与指针严格一致, 绝不跳帧
// ═══════════════════════════════════════════════════════════
let stepTimer: ReturnType<typeof setTimeout> | null = null

function togglePlay() {
  if (!allBars.value.length || phase.value === 'settled') return
  startRound()
  playing.value = !playing.value
  if (playing.value) {
    if (cursor.value >= allBars.value.length - 1) cursor.value = 0
    scheduleStep()
  } else {
    stopPlay()
  }
}

// 单拍: 推进 cursor(1根) → 同步渲染 → 调度下一拍(播放与渲染严格同步, 一根一根)
function scheduleStep() {
  if (!playing.value) return
  const interval = SPEED_MS[speed.value] ?? 600
  stepTimer = setTimeout(() => {
    stepTimer = null
    if (!playing.value) return
    if (cursor.value >= allBars.value.length - 1) {
      stopPlay()
      phase.value = 'settled'
      return
    }
    cursor.value++
    render()
    scheduleStep()
  }, interval)
}

function stopPlay() {
  playing.value = false
  if (stepTimer) { clearTimeout(stepTimer); stepTimer = null }
}

function restartTimer() {
  const wasPlaying = playing.value
  stopPlay()
  if (wasPlaying) {
    playing.value = true
    scheduleStep()
  }
}

function stepFwd() {
  if (phase.value === 'settled') return
  startRound()
  if (cursor.value < allBars.value.length - 1) {
    cursor.value++
    render()
    if (cursor.value >= allBars.value.length - 1) phase.value = 'settled'
  }
}

function stepBack() {
  if (phase.value === 'settled') return
  startRound()
  if (cursor.value > 0) {
    cursor.value--
    render()
  }
}

function onSliderInput(ev: Event) {
  if (phase.value === 'settled') return
  startRound()
  const v = Number((ev.target as HTMLInputElement).value)
  cursor.value = v
  render()
  if (v >= allBars.value.length - 1) {
    stopPlay()
    phase.value = 'settled'
  }
}

watch(speed, () => { if (playing.value) restartTimer() })
watch(cursor, () => { /* 状态栏/账户面板已由响应式驱动; 图表由 render() 显式调用 */ })

// 买入方式切换重置合理默认值
watch(sizingMode, (m) => {
  if (phase.value !== 'setup') return
  if (m === 'percent_of_equity') sizingValue.value = 0.95
  else if (m === 'fixed_capital') sizingValue.value = 50000
  else sizingValue.value = 1000
})

function fmtPct(v: number) { return (v >= 0 ? '+' : '') + (v * 100).toFixed(2) + '%' }
function fmtMoney(v: number) { return v.toLocaleString('zh-CN', { maximumFractionDigits: 0 }) }

// 主题响应 + resize
const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(() => {
  chart.value?.resize()
  render()
}) : null
let mo: MutationObserver | null = null

onMounted(() => {
  loadStrategies()
  mo = new MutationObserver(() => { if (chart.value) render() })
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

// 侧栏开合时图表尺寸自适应 + 重绘
watch(sideOpen, async () => {
  await nextTick()
  chart.value?.resize()
  render()
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
          <input v-model="code" class="code-input" placeholder="股票代码"
                 :disabled="phase !== 'setup'"
                 @keyup.enter="pickStock({ code: code, name: '', status: '' } as StockRef)"
                 @input="doSearch(code)" />
          <select v-model="strategyId" class="sel wide" :disabled="phase !== 'setup'">
            <option value="">选择策略…</option>
            <optgroup v-if="strategies.some(s => s.kind === 'family')" label="5策略家族">
              <option v-for="s in strategies.filter(x => x.kind === 'family')" :key="s.id" :value="s.id">{{ s.name }}</option>
            </optgroup>
            <optgroup v-if="strategies.some(s => s.kind === 'single')" label="LLM 生成策略">
              <option v-for="s in strategies.filter(x => x.kind === 'single')" :key="s.id" :value="s.id">{{ s.name }}</option>
            </optgroup>
          </select>
          <button class="btn primary" @click="load" :disabled="loading || !strategyId || phase !== 'setup'">
            {{ loading ? '加载中…' : '开始回放' }}
          </button>
          <span v-if="phase === 'trading'" class="tag round-tag">● 回合进行中</span>
          <span v-else-if="phase === 'settled'" class="tag round-tag done">回合已结算</span>
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

    <!-- ═══ 顶部: 回放设置(仅 setup 阶段可调) ═══ -->
    <Card class="mt" :class="{ locked: phase !== 'setup' }">
      <div class="settings-bar">
        <button class="btn" @click="settingsOpen = !settingsOpen">
          {{ settingsOpen ? '▲ 收起设置' : '▾ 回放设置' }}
        </button>
        <span class="summary muted">{{ settingsSummary }}</span>
        <span v-if="name" class="stock-name">{{ name }}</span>
        <span v-if="phase !== 'setup'" class="lock-note">
          <span class="lock-icon">🔒</span> 回合中 — 设置已锁定
        </span>
      </div>
      <div v-if="settingsOpen" class="settings-body">
        <fieldset :disabled="phase !== 'setup'" class="fs">
          <div class="settings-row">
            <div class="param-item">
              <label>起始日期</label>
              <input v-model="startDate" type="date" class="date-input" />
            </div>
            <div class="param-item">
              <label>结束日期</label>
              <input v-model="endDate" type="date" class="date-input" />
            </div>
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
              <input v-model.number="sizingValue" type="number"
                     :min="sizingMode === 'percent_of_equity' ? 0.01 : 100"
                     :step="sizingMode === 'percent_of_equity' ? 0.05 : sizingMode === 'fixed_qty' ? 100 : 10000"
                     class="num-input" />
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
          </div>
          <div class="settings-actions">
            <span v-if="!startDate && !endDate" class="muted note">未设日期时回放最近约500根K线(区间前自动预热150根因子)</span>
            <button class="btn primary" @click="load" :disabled="loading || !strategyId">应用设置并重新回放</button>
          </div>
        </fieldset>
      </div>
    </Card>

    <EmptyState v-if="errorMsg && !allBars.length" :message="errorMsg" />

    <template v-if="allBars.length">
      <!-- ═══ 中间: K线播放图 + 侧边交易明细 ═══ -->
      <div class="replay-layout mt">
        <div class="main-col">
          <Card>
            <div class="ctl">
              <button class="btn" @click="stepBack" title="上一根" :disabled="phase === 'settled'">◀</button>
              <button class="btn primary play-btn" @click="togglePlay" :disabled="phase === 'settled'">
                {{ phase === 'settled' ? '已结束' : playing ? '⏸ 暂停' : '▶ 播放' }}
              </button>
              <button class="btn" @click="stepFwd" title="下一根" :disabled="phase === 'settled'">▶</button>
              <select v-model="speed" class="sel speed-sel" title="播放速度">
                <option :value="0.25">0.25x 慢放</option>
                <option :value="0.5">0.5x</option>
                <option :value="1">1x 正常</option>
                <option :value="2">2x</option>
                <option :value="4">4x</option>
                <option :value="8">8x 快放</option>
              </select>
              <input type="range" class="slider" :min="0" :max="allBars.length - 1" :value="cursor" @input="onSliderInput" />
              <span class="mono pos">{{ cursor + 1 }}/{{ allBars.length }}</span>
              <span class="round-pct muted">{{ roundProgress }}%</span>
            </div>
            <div class="status-line">
              <span class="mono date">{{ cursorBar?.date }}</span>
              <span v-if="cursorDaily?.position" class="tag hold">● 持仓中 {{ cursorDaily?.qty }}股</span>
              <span v-else class="tag idle">○ 空仓</span>
              <span v-if="cursorDaily?.signal_buy" class="tag buy">买入信号</span>
              <span v-if="cursorDaily?.signal_sell" class="tag sell">卖出信号</span>
              <span v-if="cursorEvent" class="tag" :class="cursorEvent.kind === 'entry' ? 'buy' : 'sell'">
                {{ cursorEvent.kind === 'entry'
                  ? `▲ 建仓 @${cursorEvent.price} ×${cursorEvent.qty}股`
                  : `▼ 平仓 @${cursorEvent.price} ${cursorEvent.reason ? '(' + reasonCn(cursorEvent.reason) + ')' : ''} ${cursorEvent.net_pnl !== undefined ? '净盈亏 ' + (cursorEvent.net_pnl >= 0 ? '+' : '') + cursorEvent.net_pnl : ''}` }}
              </span>
            </div>
            <div class="chart-wrap">
              <div ref="el" class="chart"></div>
            </div>
          </Card>

          <!-- 底部: 账户 + 指标 -->
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
        </div>

        <!-- ═══ 侧边: 交易明细(可折叠) ═══ -->
        <aside class="side-col" :class="{ open: sideOpen }">
          <div class="side-toggle" @click="sideOpen = !sideOpen">
            <span class="side-toggle-txt">{{ sideOpen ? '交易明细 ▸' : '◂ 交易明细' }}</span>
            <span class="side-count" v-if="!sideOpen">{{ exitEvents.length }}</span>
          </div>
          <div v-if="sideOpen" class="side-body">
            <h4 class="side-title">交易明细 <span class="muted">({{ exitEvents.length }}笔)</span></h4>
            <div v-if="!exitEvents.length" class="side-empty muted">暂无交易</div>
            <div v-for="(e, i) in exitEvents" :key="i" class="trade-item"
                 :class="{ done: e.index <= cursor }">
              <div class="trade-head">
                <span class="trade-idx">#{{ exitEvents.length - i }}</span>
                <span class="mono muted">{{ e.entry_date }} → {{ e.date }}</span>
                <span class="trade-pnl" :class="(e.net_pnl || 0) >= 0 ? 'up' : 'down'">
                  {{ (e.net_pnl || 0) >= 0 ? '+' : '' }}{{ e.net_pnl?.toFixed(0) }}
                </span>
              </div>
              <div class="trade-body">
                <span class="mono">{{ e.entry_price }} → {{ e.price }}</span>
                <span class="tag mini" :class="e.reason === 'exit_signal' ? 'sell' : 'hold'">{{ reasonCn(e.reason || '') }}</span>
                <span class="muted tiny">持有{{ e.hold_bars }}根</span>
              </div>
              <div class="trade-meta muted tiny">毛{{ e.gross_pnl?.toFixed(0) }} · 费用{{ e.fee?.toFixed(2) }}</div>
            </div>
          </div>
        </aside>
      </div>
    </template>

    <EmptyState v-if="!allBars.length && !errorMsg && strategyId" message="选择股票和策略后点击「开始回放」" />

    <!-- ═══ 结算弹窗 ═══ -->
    <div v-if="phase === 'settled' && metrics" class="settle-overlay">
      <div class="settle-modal">
        <div class="settle-head">
          <h3>📊 回合结算</h3>
          <span class="muted">{{ name }} · {{ strategyName }}</span>
        </div>
        <div class="settle-range mono muted">
          {{ allBars[0]?.date }} ~ {{ allBars[allBars.length - 1]?.date }} · {{ allBars.length }} 根K线
        </div>
        <div class="settle-hero">
          <div class="settle-main" :class="metrics.total_return >= 0 ? 'up' : 'down'">
            {{ fmtPct(metrics.total_return) }}
          </div>
          <div class="settle-main-sub muted">区间总收益</div>
        </div>
        <div class="settle-grid">
          <div class="settle-cell">
            <div class="k muted">期初资金</div>
            <div class="v mono">{{ fmtMoney(metrics.initial_balance) }}</div>
          </div>
          <div class="settle-cell">
            <div class="k muted">期末权益</div>
            <div class="v mono" :class="metrics.final_equity >= metrics.initial_balance ? 'up' : 'down'">{{ fmtMoney(metrics.final_equity) }}</div>
          </div>
          <div class="settle-cell">
            <div class="k muted">交易次数</div>
            <div class="v mono">{{ metrics.num_trades }}</div>
          </div>
          <div class="settle-cell">
            <div class="k muted">胜率</div>
            <div class="v mono">{{ (metrics.win_rate * 100).toFixed(1) }}%</div>
          </div>
          <div class="settle-cell">
            <div class="k muted">盈亏比</div>
            <div class="v mono">{{ metrics.profit_factor }}</div>
          </div>
          <div class="settle-cell">
            <div class="k muted">最大回撤</div>
            <div class="v mono down">{{ (metrics.max_drawdown * 100).toFixed(1) }}%</div>
          </div>
          <div class="settle-cell">
            <div class="k muted">累计费用</div>
            <div class="v mono muted">{{ fmtMoney(metrics.cum_fee) }}</div>
          </div>
          <div class="settle-cell">
            <div class="k muted">已实现盈亏</div>
            <div class="v mono" :class="metrics.realized_pnl >= 0 ? 'up' : 'down'">{{ metrics.realized_pnl >= 0 ? '+' : '' }}{{ fmtMoney(metrics.realized_pnl) }}</div>
          </div>
        </div>
        <div class="settle-actions">
          <button class="btn" @click="phase = 'trading'">返回查看图表</button>
          <button class="btn primary" @click="newRound">开始新回合</button>
        </div>
      </div>
    </div>
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
.date-input { width: 148px; }
.num-input { width: 110px; }
.code-input:focus, .sel:focus, .date-input:focus, .num-input:focus { border-color: var(--gold); outline: none; }
.code-input:disabled, .sel:disabled, .date-input:disabled, .num-input:disabled,
.fs:disabled { opacity: .55; cursor: not-allowed; }
.btn {
  background: var(--bg); border: 1px solid var(--border); border-radius: var(--radius-sm);
  padding: 6px 12px; color: var(--text); cursor: pointer; font-size: var(--fs-sm);
}
.btn:hover:not(:disabled) { border-color: var(--gold); }
.btn:disabled { opacity: .45; cursor: not-allowed; }
.btn.primary { background: var(--gold); color: #1A1D23; border-color: var(--gold); font-weight: 600; }
.btn.primary:disabled { opacity: .5; }
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

/* ── 顶部设置卡 ── */
.settings-bar { display: flex; gap: var(--sp-3); align-items: center; flex-wrap: wrap; }
.summary { font-size: var(--fs-sm); }
.stock-name { color: var(--gold); font-size: var(--fs-sm); margin-left: auto; }
.lock-note { font-size: var(--fs-sm); color: var(--gold); display: flex; gap: 4px; align-items: center; margin-left: auto; }
.lock-icon { font-size: 12px; }
.settings-body { margin-top: var(--sp-3); padding-top: var(--sp-3); border-top: 1px solid var(--border-soft); }
.fs { border: none; padding: 0; margin: 0; }
.settings-row { display: flex; gap: var(--sp-3); flex-wrap: wrap; align-items: flex-end; }
.param-item { display: flex; flex-direction: column; gap: 4px; }
.param-item label { font-size: 12px; color: var(--text-sub); }
.settings-actions { display: flex; gap: var(--sp-3); align-items: center; margin-top: var(--sp-3); flex-wrap: wrap; }
.note { font-size: 12px; }
.round-tag { font-weight: 600; }
.round-tag.done { color: var(--text-sub); }
.card.locked { border-color: var(--gold); }

/* ── 布局: 主列 + 侧栏 ── */
.replay-layout { display: flex; gap: var(--sp-4); align-items: flex-start; }
.main-col { flex: 1; min-width: 0; }
.side-col {
  width: 300px; flex-shrink: 0;
  background: var(--panel); border: 1px solid var(--border); border-radius: var(--radius);
  overflow: hidden; transition: width var(--dur) var(--ease);
}
.side-col:not(.open) { width: 44px; }
.side-toggle {
  display: flex; align-items: center; justify-content: space-between;
  padding: 10px 12px; cursor: pointer; user-select: none;
  color: var(--text); font-size: var(--fs-sm); font-weight: 600;
  border-bottom: 1px solid var(--border-soft);
}
.side-col:not(.open) .side-toggle {
  flex-direction: column; gap: 6px; padding: 10px 8px;
  writing-mode: vertical-rl; text-orientation: mixed; height: 120px;
}
.side-toggle:hover { color: var(--gold); }
.side-count {
  background: var(--gold); color: #1A1D23; font-size: 11px; font-weight: 700;
  border-radius: 10px; padding: 1px 7px;
}
.side-body { padding: var(--sp-2); max-height: 720px; overflow-y: auto; }
.side-title { margin: var(--sp-1) 0 var(--sp-2); font-size: var(--fs-sm); color: var(--text); }
.side-empty { font-size: var(--fs-sm); padding: var(--sp-3); text-align: center; }

/* 交易条目 */
.trade-item {
  border: 1px solid var(--border-soft); border-radius: var(--radius-sm);
  padding: 8px 10px; margin-bottom: var(--sp-2); background: var(--bg);
  opacity: .45;
}
.trade-item.done { opacity: 1; border-color: var(--border); }
.trade-head { display: flex; align-items: center; gap: 8px; font-size: 12px; }
.trade-idx { color: var(--gold); font-weight: 700; font-family: var(--font-mono); }
.trade-head .mono { flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.trade-pnl { font-weight: 700; font-family: var(--font-mono); font-size: 13px; }
.trade-body { display: flex; gap: 8px; align-items: center; margin-top: 4px; font-size: 12px; }
.trade-meta { margin-top: 3px; }
.tiny { font-size: 11px; }
.tag.mini { padding: 1px 6px; font-size: 11px; }

/* ── 播放控制 ── */
.ctl { display: flex; gap: var(--sp-2); align-items: center; flex-wrap: wrap; padding-bottom: var(--sp-2); }
.play-btn { min-width: 96px; }
.speed-sel { width: 104px; }
.slider { flex: 1; min-width: 120px; accent-color: var(--gold); }
.pos { font-size: var(--fs-sm); color: var(--text-sub); white-space: nowrap; }
.round-pct { font-size: 12px; white-space: nowrap; }
.status-line {
  display: flex; gap: var(--sp-3); align-items: center; flex-wrap: wrap;
  font-size: var(--fs-sm); padding: var(--sp-2) 0;
  border-top: 1px solid var(--border-soft); border-bottom: 1px solid var(--border-soft);
  margin-bottom: var(--sp-2);
}
.date { color: var(--gold); font-weight: 600; }
.mono { font-family: var(--font-mono); }
.tag { padding: 2px 8px; border-radius: 10px; font-size: 12px; background: var(--bg-hover); color: var(--text-sub); }
.tag.hold { background: rgba(45,183,87,.15); color: var(--down); }
.tag.idle { background: rgba(138,143,154,.15); }
.tag.buy { background: rgba(45,183,87,.2); color: var(--down); font-weight: 600; }
.tag.sell { background: rgba(232,64,64,.2); color: var(--up); font-weight: 600; }

/* ── 图表 ── */
.chart-wrap { position: relative; width: 100%; }
.chart { width: 100%; height: 540px; min-height: 380px; }

/* ── 账户/指标卡 ── */
.acct-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: var(--sp-3); }
.metric-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: var(--sp-3); }
.metric-label { font-size: var(--fs-sm); color: var(--text-sub); }
.metric-val { font-size: 18px; font-weight: 600; color: var(--text); margin-top: 4px; }
.metric-sub { font-size: 12px; margin-top: 2px; }
.up { color: var(--up); }
.down { color: var(--down); }
.muted { color: var(--text-faint); }

/* ── 结算弹窗 ── */
.settle-overlay {
  position: fixed; inset: 0; z-index: 100;
  background: rgba(10, 12, 16, .72);
  display: flex; align-items: center; justify-content: center;
  animation: fadeIn .18s var(--ease);
}
.settle-modal {
  width: 520px; max-width: 92vw; max-height: 86vh; overflow-y: auto;
  background: var(--panel); border: 1px solid var(--gold);
  border-radius: var(--radius); padding: var(--sp-5);
  box-shadow: var(--shadow-lg);
  animation: popIn .2s var(--ease);
}
.settle-head { display: flex; align-items: baseline; gap: var(--sp-3); }
.settle-head h3 { margin: 0; font-size: 20px; }
.settle-range { margin-top: 6px; font-size: 12px; }
.settle-hero { text-align: center; margin: var(--sp-4) 0; }
.settle-main { font-size: 44px; font-weight: 700; font-family: var(--font-mono); }
.settle-main-sub { font-size: var(--fs-sm); margin-top: 2px; }
.settle-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: var(--sp-3); }
.settle-cell { background: var(--bg); border-radius: var(--radius-sm); padding: var(--sp-3); text-align: center; }
.settle-cell .k { font-size: 12px; margin-bottom: 4px; }
.settle-cell .v { font-size: 16px; font-weight: 600; }
.settle-actions { display: flex; gap: var(--sp-3); justify-content: flex-end; margin-top: var(--sp-4); }
.settle-actions .btn { padding: 8px 18px; }
@keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
@keyframes popIn { from { opacity: 0; transform: scale(.94); } to { opacity: 1; transform: scale(1); } }

@media (max-width: 1200px) {
  .acct-grid, .metric-grid { grid-template-columns: repeat(2, 1fr); }
  .replay-layout { flex-direction: column; }
  .side-col, .side-col:not(.open) { width: 100%; }
}
</style>
