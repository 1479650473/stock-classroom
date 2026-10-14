<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref, watch, nextTick } from 'vue'

// 嵌入模式: 隐藏页面标题, 只保留操作区(供策略页 Tab 内嵌)
withDefaults(defineProps<{ embedded?: boolean }>(), { embedded: false })
import * as echarts from 'echarts/core'
import { CandlestickChart, BarChart, LineChart, CustomChart } from 'echarts/charts'
import {
  TooltipComponent, GridComponent, DataZoomComponent, MarkPointComponent, MarkAreaComponent, MarkLineComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import PageHeader from '@/components/PageHeader.vue'
import Card from '@/components/Card.vue'
import EmptyState from '@/components/EmptyState.vue'
import EmptyGuide from '@/components/ui/EmptyGuide.vue'
import Icon from '@/components/Icon.vue'
import { searchStock, getReplayStrategies, getReplay } from '@/api'
import type { ReplayStrategy, ReplayResult, StockRef } from '@/api'
import { cssVar } from '@/composables/useEChart'
import { chartTokens, maColors } from '@/lib/chartTheme'

echarts.use([
  CandlestickChart, BarChart, LineChart, CustomChart,
  TooltipComponent, GridComponent, DataZoomComponent, MarkPointComponent, MarkAreaComponent, MarkLineComponent,
  CanvasRenderer,
])

// ── 数据结构 ──
interface ReplayBar {
  date: string; open: number; high: number; low: number; close: number; volume: number
  ma5?: number | null; ma10?: number | null; ma20?: number | null; ma60?: number | null
}
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
const codeInputEl = ref<HTMLInputElement>()
/** 空状态里的「选股票」入口：把焦点送回顶栏输入框，省得用户自己找 */
function focusCode() {
  codeInputEl.value?.focus()
  codeInputEl.value?.select()
}
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
// 上下文K线(起始日期之前的历史段): 仅展示用于判断所处阶段, 不参与交易回放
const contextBars = ref<ReplayBar[]>([])
const contextLen = computed(() => contextBars.value.length)

// ── 播放指针(全局索引, 0-based) ──
const cursor = ref(0)

// 图表
const el = ref<HTMLDivElement>()
const chart = ref<echarts.ECharts | null>(null)
const isDark = computed(() => document.documentElement.getAttribute('data-theme') !== 'ivory')

// ── 自适应尺寸: 容器宽度决定 K线根数(每根恒定宽度不压缩) + 窄模式隐藏辅助子图 ──
const chartW = ref(0)
const chartH = ref(0)
const K_BAR = 10                      // 每根K线目标宽度(px)
const MAX_BARS = 90                   // 最宽时最多显示根数
const MIN_BARS = 12                   // 最窄时最少显示根数(保证可读性,宽时>12)
const compactMode = ref(false)        // 窄模式: 隐藏成交量/权益子图, 保K线可读

function updateChartSize() {
  if (!el.value) return
  chartW.value = el.value.clientWidth
  chartH.value = el.value.clientHeight
  compactMode.value = chartW.value < 480
}

// 窗口随宽度自适应: 数量=能容纳的根数(宽度/每根), K 线宽度恒定不压缩
// 渲染窗口严格裁剪到播放头(end=cur): 未来K线不可见, 右侧空槽(blanks)纯留白
function getWindow(): { start: number; end: number; winSize: number; blanks: number } {
  const len = allBars.value.length
  if (!len) return { start: 0, end: 0, winSize: 0, blanks: 0 }
  const cur = Math.min(cursor.value, len - 1)
  const w = chartW.value || 800
  // 可用绘图宽度 = 容器减去 yAxis 标签等 (~80px)
  const availW = Math.max(80, w - 80)
  // 按目标宽度 K_BAR 计算能放多少根, 但最少 MIN_BARS 根
  const winSize = Math.max(MIN_BARS, Math.min(MAX_BARS, Math.floor(availW / K_BAR)))
  // 播放头固定在窗口右缘: 左端留 winSize-1 根历史, 右端绝不越界到未来
  const start = Math.max(0, cur - (winSize - 1))
  const end = cur
  const blanks = Math.max(0, winSize - (end - start + 1))
  return { start, end, winSize, blanks }
}

// 播放
const playing = ref(false)
const speed = ref(1)
const SPEED_MS: Record<number, number> = { 0.25: 2400, 0.5: 1200, 1: 600, 2: 300, 4: 150, 8: 75 }

// 侧栏(交易明细)
const sideOpen = ref(true)

// ── 当前状态(供面板/状态栏) ──
// allBars 含上下文段(前 contextLen 根), 而 daily/events/spans 均为展示区相对索引,
// 统一换算: chartIdx = dispIdx + contextLen
const cursorBar = computed(() => allBars.value[cursor.value])
const cursorDaily = computed(() =>
  cursor.value >= contextLen.value ? allDaily.value[cursor.value - contextLen.value] : undefined)
const cursorEvent = computed(() =>
  allEvents.value.find((e) => e.index === cursor.value - contextLen.value))

const holdingState = computed(() => {
  const d = cursorDaily.value
  if (!d || !d.position) return null
  const bars = (cursor.value - contextLen.value - (d.entry_index >= 0 ? d.entry_index : 0)) + 1
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

// 回合进度(仅展示区, 不含上下文段)
const roundProgress = computed(() => {
  const denom = allBars.value.length - contextLen.value - 1
  return denom > 0 ? Math.round(((cursor.value - contextLen.value) / denom) * 100) : 0
})

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

// 设置快照: 记录最近一次加载所用设置, 检测「改了设置但未重新加载」的情况
const loadedSig = ref('')
const settingsDirty = computed(() =>
  allBars.value.length > 0 && JSON.stringify(buildQuery()) !== loadedSig.value)

async function load() {
  if (!code.value || !strategyId.value) return
  loading.value = true
  errorMsg.value = ''
  stopPlay()
  phase.value = 'setup'
  try {
    const r = await getReplay(code.value, strategyId.value, 2500, buildQuery())
    contextBars.value = r.context_bars ?? []
    allBars.value = [...contextBars.value, ...r.bars]
    allDaily.value = r.daily
    allEvents.value = r.events
    allSpans.value = r.holding_spans
    metrics.value = r.metrics
    cursor.value = contextLen.value   // 播放头定位到展示区起点(起始日期), 其左为上下文历史
    loadedSig.value = JSON.stringify(buildQuery())
    await nextTick()
    // 单一初始化路径: 首次创建图表, 重载时强制全量重建(避免 dispose+重建竞态)
    if (chart.value) {
      lastStruct = ''
      render()
    } else if (el.value) {
      initChart()
    }
  } catch (e) {
    errorMsg.value = e instanceof Error ? e.message : '加载失败'
    allBars.value = []
    allDaily.value = []
    contextBars.value = []
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
  cursor.value = contextLen.value
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
  const _t = chartTokens()
  const gridText = _t.textSub
  const gridLine = _t.borderSoft
  const maCol = maColors()

  const { start, end, blanks } = getWindow()
  const bars = allBars.value.slice(start, end + 1)
  const total = bars.length
  if (!total) return {}
  // 轴保留全部槽位(空串占位=右侧留白); 系列 data 只给已播放段 —
  // ⚠ candlestick(boxplot底层) data 混入 null 会抛错, 不能补位
  const dates = [...bars.map((b) => b.date), ...Array<string>(blanks).fill('')]
  const ohlc = bars.map((b) => [b.open, b.close, b.low, b.high])
  const volumes = bars.map((b) => b.volume)
  const colors = bars.map((b) => (b.close >= b.open ? upColor : downColor))
  const curLocal = cursor.value - start   // 播放头=窗口右缘

  // MA 值由后端在含预热段的完整序列上计算(播放头第一根即有值), 前端直接取用
  const maData = (n: 5 | 20) => bars.map((b) => b[`ma${n}`] ?? null)

  // 买卖点(仅当前窗口内的, 保留全部标记便于观察; 事件索引为展示区相对 → +contextLen 换算)
  const markPoints: { coord: [number, number]; value: string; symbol: string; symbolSize: number; itemStyle: { color: string } }[] = []
  for (const e of allEvents.value) {
    const ci = e.index + contextLen.value
    if (ci < start || ci > end) continue
    const local = ci - start
    if (e.kind === 'entry') {
      markPoints.push({ coord: [local, e.price], value: 'B', symbol: 'pin', symbolSize: 24, itemStyle: { color: cssVar('--up') } })
    } else {
      markPoints.push({ coord: [local, e.price], value: 'S', symbol: 'pin', symbolSize: 24, itemStyle: { color: cssVar('--down') } })
    }
  }

  // 持仓区间(裁剪到窗口; 仅显示已发生的持仓段)
  const markAreas: Array<Array<{ xAxis: number; itemStyle?: { color: string } }>> = []
  for (const [s, e] of allSpans.value) {
    const cs = s + contextLen.value
    const ce = Math.min(e, cursor.value - contextLen.value) + contextLen.value
    if (ce < start || cs > end) continue
    const ls = Math.max(cs, start)
    const le = Math.min(ce, end)
    if (le < ls) continue
    markAreas.push([
      { xAxis: ls - start, itemStyle: { color: 'rgba(45,183,87,0.13)' } },
      { xAxis: le - start },
    ])
  }

  // 上下文段底色(起始日期之前的历史, 仅展示): 与回放区区分, 播放头竖线为分界
  if (contextLen.value > 0) {
    const cs = Math.max(0, start)
    const ce = Math.min(contextLen.value - 1, end)
    if (ce >= cs) {
      markAreas.push([
        { xAxis: cs - start, itemStyle: { color: 'rgba(138,143,154,0.10)' } },
        { xAxis: ce - start },
      ])
    }
  }

  // 播放头竖线
  const markLines = [
    { xAxis: curLocal, lineStyle: { color: cssVar('--gold'), type: 'dashed' as const, width: 1 } },
  ]

  // 窄模式: 只保留 K 线主图(成交量/权益子图隐藏), K 线不横向压缩
  const compact = compactMode.value
  const grids = compact
    ? [{ left: 60, right: 20, top: 20, bottom: 40 }]
    : [
        { left: 60, right: 20, top: 20, height: '52%' },
        { left: 60, right: 20, top: '70%', height: '12%' },
        { left: 60, right: 20, top: '85%', height: '8%' },
      ]
  const xAxes = compact
    ? [{
        type: 'category', data: dates, gridIndex: 0,
        axisLine: { lineStyle: { color: gridLine } },
        axisLabel: { color: gridText, fontSize: 10 },
        splitLine: { show: false },
      }]
    : [
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
      ]
  const yAxes = compact
    ? [{
        type: 'value', gridIndex: 0, scale: true,
        splitLine: { lineStyle: { color: gridLine, type: 'dashed' } },
        axisLabel: { color: gridText, fontSize: 10 },
      }]
    : [
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
      ]

  const series: unknown[] = [{
    id: 'candlestick',
    type: 'candlestick',
    xAxisIndex: 0, yAxisIndex: 0,
    data: ohlc,
    barWidth: K_BAR,
    itemStyle: { color: upColor, color0: downColor, borderColor: upColor, borderColor0: downColor },
    markArea: { silent: true, data: markAreas },
    markPoint: {
      symbol: 'pin', symbolSize: 24, data: markPoints,
      label: { show: true, color: '#fff', fontSize: 9, fontWeight: 'bold' },
      itemStyle: { borderColor: '#fff', borderWidth: 1 },
    },
    markLine: { silent: true, symbol: 'none', data: markLines },
  }]
  series.push({ name: 'MA5', type: 'line', xAxisIndex: 0, yAxisIndex: 0, data: maData(5), smooth: true, symbol: 'none', lineStyle: { width: 1, color: maCol[0] } })
  series.push({ name: 'MA20', type: 'line', xAxisIndex: 0, yAxisIndex: 0, data: maData(20), smooth: true, symbol: 'none', lineStyle: { width: 1, color: maCol[1] } })
  if (!compact) {
    series.push({
      type: 'bar',
      xAxisIndex: 1, yAxisIndex: 1,
      data: volumes.map((v, i) => ({ value: v, itemStyle: { color: colors[i] + '88' } })),
      barWidth: 6,
    })
    series.push({
      name: '权益',
      type: 'line',
      xAxisIndex: 2, yAxisIndex: 2,
      data: bars.map((_, i) => allDaily.value[start + i]?.equity ?? null),
      symbol: 'none',
      lineStyle: { width: 1.2, color: _t.accent },
      areaStyle: { color: 'rgba(91,143,249,0.12)' },
    })
  }

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
        const p = params[0] as { dataIndex: number; data: number[]; axisValue: string }
        const b = bars[p.dataIndex]
        if (!b) return ''
        const chg = ((b.close - b.open) / b.open * 100).toFixed(2)
        const color = b.close >= b.open ? upColor : downColor
        const absIdx = start + p.dataIndex          // 图表坐标(含上下文段)
        const dispIdx = absIdx - contextLen.value   // 展示区相对
        const d = dispIdx >= 0 ? allDaily.value[dispIdx] : undefined
        const posTag = d?.position ? `<span style="color:${cssVar('--down')}">●持仓</span>` : ''
        const sig = d?.signal_buy ? ` <b style="color:${cssVar('--up')}">买入信号</b>`
          : d?.signal_sell ? ` <b style="color:${cssVar('--down')}">卖出信号</b>` : ''
        const ev = dispIdx >= 0 ? allEvents.value.find((x) => x.index === dispIdx) : undefined
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
    ...(compact ? {} : { axisPointer: { link: [{ xAxisIndex: [0, 1, 2] }] } }),
    grid: grids,
    xAxis: xAxes,
    yAxis: yAxes,
    series,
  }
}


function reasonCn(r: string): string {
  const m: Record<string, string> = {
    stop_loss: '止损', take_profit: '止盈', trailing_stop: '移动止损',
    time_limit: '时间止损', exit_signal: '策略卖出',
  }
  return m[r] || r
}

// 渲染入口: 播放拍/单步/拖动用同步渲染(确定性, 与指针严格一致);
// 尺寸/主题等低频变更经 rAF 合并到同一帧(多来源去重, 避免双重重绘卡顿)
let rafId: number | null = null
let lastStruct = ''
let reinitFails = 0   // setOption 连续失败计数: 超过上限停止重建, 防止死循环冻结页面

function render() {
  doRender()
}

function doRender() {
  if (!chart.value || !allBars.value.length) return
  // 容器未布局(宽为0)时跳过, 待 ResizeObserver 回调再画, 避免空白帧
  if (el.value && el.value.clientWidth === 0) return
  if (reinitFails > 2) return
  const struct = `${compactMode.value}|${chartW.value}`
  try {
    if (struct !== lastStruct) {
      // 结构变化(grid/x/y轴数量/窗口容量): 全量重建一次, 避免 merge 残留
      lastStruct = struct
      chart.value.setOption(buildOption(), true)
    } else {
      // 播放拍: merge 增量 — tooltip/axisPointer 保持单例不重建(避免标签堆积),
      // 且只 diff 变化的K线/标记, 更流畅
      chart.value.setOption(buildOption(), { notMerge: false })
    }
    reinitFails = 0
  } catch (e) {
    reinitFails++
    if (reinitFails <= 2) {
      console.warn('chart setOption failed, re-init', e)
      try { chart.value?.dispose() } catch { /* ignore */ }
      chart.value = null
      try { initChart() } catch (e2) { console.warn('chart re-init failed', e2) }
    } else {
      console.error('replay chart repeatedly failed, rendering stopped', e)
    }
  }
}

// 多来源(RO/主题/侧栏开合)合并到同一帧, 每帧最多画一次
function scheduleRender() {
  if (rafId !== null) return
  rafId = requestAnimationFrame(() => {
    rafId = null
    render()
  })
}

function initChart() {
  if (!el.value) return
  if (chart.value) { chart.value.dispose(); chart.value = null }
  updateChartSize()
  chart.value = echarts.init(el.value, undefined, { renderer: 'canvas' })
  doRender()
  if (ro && el.value) ro.observe(el.value)
}

// ═══════════════════════════════════════════════════════════
//  播放控制 — 一根一根: 每拍【推进1根 + 渲染】, 渲染完成后调度下一拍
//  不使用自转时间轴(rAF/interval), 保证渲染与指针严格一致, 绝不跳帧
// ═══════════════════════════════════════════════════════════
let stepTimer: ReturnType<typeof setTimeout> | null = null

async function togglePlay() {
  if (!allBars.value.length || phase.value === 'settled') return
  // 设置已变更未加载: 播放前自动应用(按设置日期/参数重新回放)
  if (phase.value === 'setup' && settingsDirty.value) {
    await load()
    if (!allBars.value.length) return
  }
  startRound()
  playing.value = !playing.value
  if (playing.value) {
    if (cursor.value >= allBars.value.length - 1) cursor.value = contextLen.value
    render()
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
      stopPlay()      // 停在末尾自动暂停, 不弹结算; 由用户点「✓ 结算」触发
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

async function stepFwd() {
  if (phase.value === 'setup' && settingsDirty.value) {
    await load()
    if (!allBars.value.length) return
  }
  startRound()
  if (cursor.value < allBars.value.length - 1) {
    cursor.value++
    render()
  } else {
    settle()      // 已到末尾: 用户显式确认 → 弹结算
  }
}

function settle() {
  stopPlay()
  phase.value = 'settled'
  render()
}

function stepBack() {
  startRound()
  if (cursor.value > contextLen.value) {   // 只回退到展示区起点, 不进入上下文段
    cursor.value--
    render()
  }
}

function onSliderInput(ev: Event) {
  startRound()
  if (playing.value) stopPlay()   // 拖动即暂停: 避免进度与播放节奏冲突
  const v = Number((ev.target as HTMLInputElement).value)
  cursor.value = Math.max(contextLen.value, v)
  render()
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

// 主题响应 + resize(尺寸变化时更新窗口参数并重绘; 回调经 rAF 合并, 避免 resize+render 双重重绘)
const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(() => {
  updateChartSize()
  chart.value?.resize()
  scheduleRender()
}) : null
let mo: MutationObserver | null = null

onMounted(() => {
  loadStrategies()
  mo = new MutationObserver(() => { if (chart.value) scheduleRender() })
  mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
})

onBeforeUnmount(() => {
  stopPlay()
  if (rafId !== null) { cancelAnimationFrame(rafId); rafId = null }
  ro?.disconnect()
  mo?.disconnect()
  chart.value?.dispose()
})

// 侧栏开合时图表尺寸自适应 + 重绘
watch(sideOpen, async () => {
  await nextTick()
  updateChartSize()
  chart.value?.resize()
  scheduleRender()
})

watch(strategyId, (v) => {
  if (v && code.value) load()
})
</script>

<template>
  <div>
    <PageHeader title="策略回放" subtitle="真实交易环境模拟 — 逐日播放买卖点 / 持仓盈亏 / 账户权益" :embedded="embedded">
      <template #right>
        <div class="hdr-actions">
          <input v-model="code" ref="codeInputEl" class="code-input" placeholder="股票代码"
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
          <Icon :name="settingsOpen ? 'chevron-up' : 'chevron-down'" :size="14" />
          {{ settingsOpen ? '收起设置' : '回放设置' }}
        </button>
        <span class="summary muted">{{ settingsSummary }}</span>
        <span v-if="settingsDirty" class="tag dirty-note">
          <Icon name="alert" :size="12" /> 设置已变更 · 播放时自动应用
        </span>
        <span v-if="name" class="stock-name">{{ name }}</span>
        <span v-if="phase !== 'setup'" class="lock-note">
          <Icon name="alert" :size="12" /> 回合中 — 设置已锁定
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
            <span class="muted note">起始日期前的历史K线作为上下文一并显示(左侧浅色区, 便于判断所处阶段), 不参与交易回放</span>
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
              <button class="btn" @click="stepBack" title="上一根" :disabled="phase === 'settled'">
                <Icon name="chevron-left" :size="14" />
              </button>
              <button class="btn primary play-btn" @click="togglePlay" :disabled="phase === 'settled'">
                <!-- icons.ts 里没有 pause，用 stop 表示"停下来"（按钮本身有文字，不会歧义） -->
                <Icon :name="playing && phase !== 'settled' ? 'stop' : 'play'" :size="14" />
                {{ phase === 'settled' ? '已结束' : playing ? '暂停' : '播放' }}
              </button>
              <button class="btn" @click="stepFwd"
                      :title="phase === 'trading' && cursor >= allBars.length - 1 ? '结算本轮' : '下一根'"
                      :disabled="phase === 'settled'">
                <template v-if="phase === 'trading' && cursor >= allBars.length - 1">
                  <Icon name="check" :size="14" /> 结算
                </template>
                <Icon v-else name="chevron-right" :size="14" />
              </button>
              <select v-model="speed" class="sel speed-sel" title="播放速度">
                <option :value="0.25">0.25x 慢放</option>
                <option :value="0.5">0.5x</option>
                <option :value="1">1x 正常</option>
                <option :value="2">2x</option>
                <option :value="4">4x</option>
                <option :value="8">8x 快放</option>
              </select>
              <input type="range" class="slider" :min="contextLen" :max="allBars.length - 1" :value="cursor" @input="onSliderInput" />
              <span class="mono pos">{{ cursor + 1 - contextLen }}/{{ allBars.length - contextLen }}</span>
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
                 :class="{ done: e.index + contextLen <= cursor }">
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

    <!-- 首次进入的引导：不只说"没数据"，而是把三步流程和入口直接给出来 -->
    <EmptyGuide
      v-if="!allBars.length && !errorMsg"
      icon="play"
      title="还没有回放结果"
      desc="按顺序完成三步：① 在顶栏选一只股票 ② 选一个策略 ③ 点「开始回放」。回放会逐日播放买卖点、持仓盈亏与账户权益，并在回合结束时给出结算。"
    >
      <template #action>
        <div class="guide-actions">
          <button class="btn primary" @click="focusCode">去选股票</button>
          <button class="btn" @click="settingsOpen = true">回放设置</button>
        </div>
      </template>
    </EmptyGuide>

    <!-- ═══ 结算弹窗 ═══ -->
    <div v-if="phase === 'settled' && metrics" class="settle-overlay">
      <div class="settle-modal">
        <div class="settle-head">
          <h3><Icon name="check" :size="16" /> 回合结算</h3>
          <span class="muted">{{ name }} · {{ strategyName }}</span>
        </div>
        <div class="settle-range mono muted">
          {{ allBars[contextLen]?.date }} ~ {{ allBars[allBars.length - 1]?.date }} · {{ allBars.length - contextLen }} 根K线
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
/* 设置区的操作行：说明文字独占一行，按钮另起一行靠右。
   原来是 flex+wrap 把「说明」和「应用设置并重新回放」塞在同一行 ——
   1600 宽下两者挤在一起、按钮被压得又小又贴边（实测截图可见）。 */
.settings-actions {
  display: flex; flex-direction: column; align-items: flex-end;
  gap: var(--sp-3); margin-top: var(--sp-4);
}
.settings-actions .note { align-self: stretch; line-height: 1.6; }
.note { font-size: 12px; }
.guide-actions { display: flex; gap: var(--sp-3); justify-content: center; flex-wrap: wrap; }
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
.dirty-note { background: rgba(232,181,75,.18); color: var(--gold); font-weight: 600; }

/* ── 图表 ── */
.chart-wrap { position: relative; width: 100%; }
.chart { width: 100%; min-height: 380px; height: clamp(380px, 55vh, 640px); }

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
  .replay-layout { flex-direction: column; align-items: stretch; }
  .main-col { width: 100%; }
  .side-col, .side-col:not(.open) { width: 100%; }
}
</style>
