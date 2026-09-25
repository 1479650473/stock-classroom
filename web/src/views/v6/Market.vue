<script setup lang="ts">
import { computed, onActivated, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppPage from '@/components/ui/AppPage.vue'
import PageToolbar from '@/components/ui/PageToolbar.vue'
import SectionCard from '@/components/ui/SectionCard.vue'
import DataTable from '@/components/ui/DataTable.vue'
import type { DataColumn } from '@/components/ui/DataTable.vue'
import SearchInput from '@/components/ui/SearchInput.vue'
import EmptyGuide from '@/components/ui/EmptyGuide.vue'
import LoadingBlock from '@/components/ui/LoadingBlock.vue'
import SegmentedControl from '@/components/ui/SegmentedControl.vue'
import KlineChart from '@/components/charts/KlineChart.vue'
import EtfPanel from '@/components/EtfPanel.vue'
import Icon from '@/components/Icon.vue'
import { getIndices, getSectors, getNorthFlow, getKline, getKlineMinute, getKlineAnalysis, getCyq, searchStock, getFundFlow } from '@/api'
import type { IndexQuote, KlineBar, KlinePeriod, MinuteBar, StockRef, FundFlowBar, AutoAnalysis } from '@/api'
import { SUB_SPECS } from '@/lib/indicators'
import type { ChipRow } from '@/lib/indicators'
import { usePersistedRef } from '@/composables/usePersistedRef'

type Tab = 'market' | 'stock' | 'etf'
type Period = 'ts' | '1' | '5' | '15' | '30' | '60' | 'daily' | 'weekly' | 'monthly'

const route = useRoute()
const router = useRouter()

const TABS = [
  { value: 'market', label: '市场', icon: 'market' },
  { value: 'stock', label: '个股', icon: 'kline' },
  { value: 'etf', label: 'ETF', icon: 'kline' },
]

const tab = ref<Tab>(route.query.tab === 'stock' ? 'stock' : route.query.tab === 'etf' ? 'etf' : 'market')
// 记住上次查看的股票与周期，下次打开自动恢复
const code = usePersistedRef('market.code', String(route.query.code || ''))
const stockName = ref(String(route.query.name || ''))
const days = usePersistedRef('market.days', '250')
const period = usePersistedRef<Period>('market.period', 'daily')

const PERIOD_OPTIONS = [
  { value: 'ts', label: '分时' },
  { value: '1', label: '1分' },
  { value: '5', label: '5分' },
  { value: '15', label: '15分' },
  { value: '30', label: '30分' },
  { value: '60', label: '60分' },
  { value: 'daily', label: '日K' },
  { value: 'weekly', label: '周K' },
  { value: 'monthly', label: '月K' },
]
type SubKind = 'macd' | 'kdj' | 'rsi' | 'obv' | 'cci' | 'wr' | 'dmi' | 'bias' | 'atr' | 'psy' | 'vr' | 'trix' | 'mtm' | 'arbr' | 'roc' | 'zj' | 'none'
const SUB_OPTIONS = [
  { value: 'macd', label: 'MACD' },
  { value: 'kdj', label: 'KDJ' },
  { value: 'rsi', label: 'RSI' },
  { value: 'obv', label: 'OBV' },
  { value: 'wr', label: 'WR' },
  { value: 'cci', label: 'CCI' },
  { value: 'dmi', label: 'DMI' },
  { value: 'bias', label: 'BIAS' },
  { value: 'psy', label: 'PSY' },
  { value: 'vr', label: 'VR' },
  { value: 'atr', label: 'ATR' },
  { value: 'trix', label: 'TRIX' },
  { value: 'mtm', label: 'MTM' },
  { value: 'arbr', label: 'ARBR' },
  { value: 'roc', label: 'ROC' },
  { value: 'zj', label: '庄家抬轿' },
  { value: 'none', label: '无' },
]
const MA_CHOICES = [5, 10, 20, 30, 60, 120, 250]

const indices = ref<IndexQuote[]>([])
const sectors = ref<Record<string, unknown>[]>([])
const north = ref<Record<string, unknown>[]>([])
const marketLoading = ref(true)
const marketError = ref('')

const kline = ref<KlineBar[]>([])
const klineLoading = ref(false)
const klineError = ref('')
const fundFlow = ref<FundFlowBar[]>([])
const minuteBars = ref<MinuteBar[]>([])
const prevClose = ref<number | null>(null)

// 专业控件（持久化）：副图指标 / 布林带 / 均线组
const subIndicator = usePersistedRef<SubKind>('market.sub', 'macd')
// 程序自动画线 / 自动技术分析（默认开）
const autoOn = usePersistedRef('market.auto', true)
const analysis = ref<AutoAnalysis | null>(null)
const analysisLoading = ref(false)
const bollOn = usePersistedRef('market.boll', false)
const sarOn = usePersistedRef('market.sar', false)
// 筹码分布（最新快照叠加 + 卡片）
const chipOn = usePersistedRef('market.chip', false)
const cyqRows = ref<ChipRow[]>([])
const cyq = computed(() => cyqRows.value[0] ?? null)
// 副图参数（按指标存，缺省=注册表默认值）
const subParams = usePersistedRef<Record<string, Record<string, number>>>('market.subParams', {})
const paramOpen = ref(false)
const curParams = computed(() => subParams.value[subIndicator.value] || {})
function setParam(key: string, ev: Event) {
  const v = Number((ev.target as HTMLInputElement).value)
  const kind = subIndicator.value
  const next = { ...(subParams.value[kind] || {}) }
  if (Number.isFinite(v) && v > 0) next[key] = Math.round(v)
  else delete next[key]
  subParams.value = { ...subParams.value, [kind]: next }
}
function resetParams() {
  const kind = subIndicator.value
  const next = { ...subParams.value }
  delete next[kind]
  subParams.value = next
}
/** 筹码叠加（主图线） */
const chipOverlay = computed(() => {
  const c = cyq.value
  if (!chipOn.value || !c) return null
  const avg = Number(c.avg_cost)
  const low = Number(c.cost90_low)
  const high = Number(c.cost90_high)
  if (!Number.isFinite(avg)) return null
  return { avg, low90: Number.isFinite(low) ? low : NaN, high90: Number.isFinite(high) ? high : NaN }
})
/** 筹码一句话解读 */
const chipNote = computed(() => {
  const c = cyq.value
  if (!c) return ''
  const avg = Number(c.avg_cost)
  const profit = Number(c.profit_ratio) * 100
  const conc = Number(c.conc90)
  const px = headQuote.value?.price
  const parts: string[] = []
  if (px && Number.isFinite(avg) && avg > 0) {
    const dev = (px / avg - 1) * 100
    parts.push(dev >= 0 ? `现价高于平均成本 ${dev.toFixed(1)}%` : `现价低于平均成本 ${Math.abs(dev).toFixed(1)}%`)
  }
  if (Number.isFinite(profit)) {
    parts.push(profit >= 70 ? `获利盘 ${profit.toFixed(0)}%，上方抛压相对轻`
      : profit <= 20 ? `获利盘仅 ${profit.toFixed(0)}%，反弹会遇解套盘`
        : `获利盘 ${profit.toFixed(0)}%`)
  }
  if (Number.isFinite(conc)) {
    parts.push(conc <= 0.08 ? '筹码高度集中' : conc <= 0.15 ? '筹码集中度中等' : '筹码较分散')
  }
  return parts.join('；')
})
const maSet = usePersistedRef<number[]>('market.mas', [5, 10, 20, 60])
function toggleMa(n: number) {
  const cur = maSet.value || []
  maSet.value = cur.includes(n) ? cur.filter((x) => x !== n) : [...cur, n].sort((a, b) => a - b)
}

/** 图表键盘快捷键：数字 1-9 切周期（对应 PERIOD_OPTIONS 顺序） */
function setPeriodByKey(i: number) {
  const opt = PERIOD_OPTIONS[i]
  if (opt) period.value = opt.value as Period
}

// 深链：?period=ts|1|5|15|30|60|daily|weekly|monthly、?sub=macd|kdj|rsi|none（截图/分享用）
;(() => {
  const qp = String(route.query.period || '')
  if (PERIOD_OPTIONS.some((o) => o.value === qp)) period.value = qp as Period
  const qs = String(route.query.sub || '')
  if (SUB_OPTIONS.some((o) => o.value === qs)) subIndicator.value = qs as SubKind
})()

const isMinute = computed(() => ['ts', '1', '5', '15', '30', '60'].includes(period.value))
const isTimeshare = computed(() => period.value === 'ts')
const periodLabel = computed(() =>
  PERIOD_OPTIONS.find((o) => o.value === period.value)?.label || period.value,
)

const lastBar = computed(() => kline.value[kline.value.length - 1] ?? null)

/** 资金流副图数据(主力净流入, 与K线时间对齐) */
const lwcFundFlow = computed(() =>
  fundFlow.value.map((f) => ({
    time: lwcTime(f.date),
    mainNet: f.main_net,
    mainRatio: f.main_ratio,
  })),
)

/** YYYYMMDD -> YYYY-MM-DD (lightweight-charts 要求) */
function lwcTime(d: string): string {
  return /^\d{8}$/.test(d) ? `${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6, 8)}` : d
}
/** "YYYY-MM-DD HH:MM:SS" → epoch 秒（按北京时间当 UTC 用，轴面显示才正确） */
function epTime(s: string): number {
  const m = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/.exec(s)
  if (!m) return Math.floor(Date.parse(s) / 1000)
  return Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]) / 1000
}
const lwcBars = computed(() => {
  if (isMinute.value) {
    let bars = minuteBars.value
    if (isTimeshare.value && bars.length) {
      const lastDate = bars[bars.length - 1].time.slice(0, 10)
      bars = bars.filter((b) => b.time.slice(0, 10) === lastDate)
    }
    return bars.map((b) => ({
      time: epTime(b.time),
      open: b.open,
      high: b.high,
      low: b.low,
      close: b.close,
      volume: b.volume,
      amount: b.amount,
    }))
  }
  return kline.value.map((b) => ({
    time: lwcTime(b.date),
    open: b.open,
    high: b.high,
    low: b.low,
    close: b.close,
    volume: b.volume,
    amount: b.amount,
  }))
})
/** 涨跌停阈值：主板 10%、创业板/科创 20%、北交所 30%（用于 K 线涨跌停标记） */
const limitPct = computed(() => {
  const c = String(code.value || '')
  if (c.startsWith('30') || c.startsWith('68')) return 0.198
  if (/^(43|83|87|88|92)/.test(c)) return 0.298
  return 0.098
})

const changePct = computed(() => {
  if (isMinute.value) {
    const bars = lwcBars.value
    const last = bars[bars.length - 1]
    if (!last) return 0
    const base = prevClose.value ?? bars[bars.length - 2]?.close ?? last.close
    return base ? ((last.close - base) / base) * 100 : 0
  }
  if (!lastBar.value || kline.value.length < 2) return 0
  const prev = kline.value[kline.value.length - 2].close
  return prev ? ((lastBar.value.close - prev) / prev) * 100 : 0
})
/** 头部报价（分钟模式用最后一根分钟线） */
const headQuote = computed(() => {
  if (isMinute.value) {
    const bars = lwcBars.value
    const last = bars[bars.length - 1]
    return last ? { price: last.close, high: last.high, low: last.low, open: last.open, volume: last.volume } : null
  }
  return lastBar.value
    ? { price: lastBar.value.close, high: lastBar.value.high, low: lastBar.value.low, open: lastBar.value.open, volume: lastBar.value.volume }
    : null
})

const DAY_OPTIONS = [
  { value: '60', label: '60日' },
  { value: '120', label: '120日' },
  { value: '250', label: '250日' },
  { value: '500', label: '500日' },
]

async function loadMarket(fresh = false) {
  marketLoading.value = !indices.value.length
  marketError.value = ''
  try {
    const [i, s, n] = await Promise.all([getIndices(fresh), getSectors('industry'), getNorthFlow(30)])
    indices.value = i
    sectors.value = s
    north.value = n
  } catch (e) {
    marketError.value = e instanceof Error ? e.message : '市场数据加载失败'
  } finally {
    marketLoading.value = false
  }
}

/** 程序分析（仅日/周/月线；分钟级暂不做结构分析） */
async function loadAnalysis() {
  if (!autoOn.value || !code.value || isMinute.value) {
    analysis.value = null
    return
  }
  analysisLoading.value = true
  try {
    analysis.value = await getKlineAnalysis(code.value, period.value as KlinePeriod, Number(days.value))
  } catch {
    analysis.value = null
  } finally {
    analysisLoading.value = false
  }
}

async function loadChips() {
  // 筹码序列：筹码叠加开关 或 庄家抬轿指标 需要
  const need = chipOn.value || subIndicator.value === 'zj'
  if (!need || !code.value) {
    cyqRows.value = []
    return
  }
  try {
    const rows = (await getCyq(code.value)) || []
    cyqRows.value = rows.map((r) => ({
      date: String(r.date || ''),
      profit_ratio: Number(r.profit_ratio),
      avg_cost: Number(r.avg_cost),
      conc70: Number(r.conc70),
      conc90: Number(r.conc90),
      cost70_low: Number(r.cost70_low),
      cost70_high: Number(r.cost70_high),
      cost90_low: Number(r.cost90_low),
      cost90_high: Number(r.cost90_high),
    }))
  } catch {
    cyqRows.value = []
  }
}

async function loadKline() {
  if (!code.value) return
  klineLoading.value = true
  klineError.value = ''
  try {
    if (isMinute.value) {
      const r = await getKlineMinute(code.value, isTimeshare.value ? '1' : period.value, 0)
      minuteBars.value = r?.bars || []
      prevClose.value = r?.prev_close ?? null
      kline.value = []
      fundFlow.value = []
    } else {
      const [bars, ff] = await Promise.all([
        getKline(code.value, Number(days.value), period.value as KlinePeriod),
        period.value === 'daily'
          ? getFundFlow(code.value, Number(days.value)).catch(() => [] as FundFlowBar[])
          : Promise.resolve([] as FundFlowBar[]),
      ])
      kline.value = bars
      fundFlow.value = ff
      minuteBars.value = []
      prevClose.value = null
    }
  } catch (e) {
    klineError.value = e instanceof Error ? e.message : 'K线加载失败'
    kline.value = []
    minuteBars.value = []
  } finally {
    klineLoading.value = false
    void loadAnalysis()
    void loadChips()
  }
}

function onPick(s: StockRef) {
  code.value = s.code
  stockName.value = s.name
  tab.value = 'stock'
  loadKline()
}

async function resolveStockName() {
  if (!code.value || stockName.value) return
  try {
    const rows = await searchStock(code.value)
    const hit = rows.find((r) => r.code === code.value)
    if (hit?.name) stockName.value = hit.name
  } catch {
    /* 名称解析失败不影响 K 线展示 */
  }
}

function onSubmit(c: string) {
  if (!c) return
  code.value = c
  tab.value = 'stock'
  loadKline()
}

watch(tab, (v) => {
  router.replace({ query: { ...route.query, tab: v } })
})
watch(days, () => { if (code.value) loadKline() })
watch(autoOn, () => { void loadAnalysis() })
watch(chipOn, () => { void loadChips() })
watch(subIndicator, () => { void loadChips() })
watch(period, () => { if (code.value) loadKline() })
watch(
  () => route.query,
  (q) => {
    if (q.tab === 'stock' && tab.value !== 'stock') tab.value = 'stock'
    const qp = String(q.period || '')
    if (qp && PERIOD_OPTIONS.some((o) => o.value === qp) && qp !== period.value) period.value = qp as Period
    if (q.code && String(q.code) !== code.value) {
      code.value = String(q.code)
      stockName.value = String(q.name || '')
      tab.value = 'stock'
      loadKline()
      resolveStockName()
    }
  },
)

function fmtPct(v: number) { return (v >= 0 ? '+' : '') + v.toFixed(2) + '%' }
function fmtNum(v: number) {
  const n = Math.abs(v) < 0.005 ? 0 : v
  return n.toFixed(2)
}

const sectorColumns: DataColumn[] = [
  { key: 'name', title: '板块' },
  { key: 'change_pct', title: '涨跌幅', align: 'right', sortable: true },
]

const northColumns: DataColumn[] = [
  { key: 'date', title: '日期' },
  { key: 'net_flow', title: '净流入（亿）', align: 'right', sortable: true },
]

const klineColumns: DataColumn[] = [
  {
    key: 'date',
    title: '日期',
    format: (r) => {
      const s = String(r.date || '')
      return /^\d{8}$/.test(s) ? `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)}` : s
    },
  },
  { key: 'open', title: '开盘', align: 'right', format: (r) => Number(r.open).toFixed(2) },
  { key: 'high', title: '最高', align: 'right', format: (r) => Number(r.high).toFixed(2) },
  { key: 'low', title: '最低', align: 'right', format: (r) => Number(r.low).toFixed(2) },
  { key: 'close', title: '收盘', align: 'right', format: (r) => Number(r.close).toFixed(2) },
  { key: 'volume', title: '成交量', align: 'right', format: (r) => Number(r.volume).toLocaleString() },
]

const klineRows = computed(() => [...kline.value].reverse() as unknown as Record<string, unknown>[])

onActivated(() => {
  // 切回行情页：指数有 TTL（30s），过期才真正请求；K 线按当前选中代码保持
  loadMarket()
})

onMounted(() => {
  loadMarket()
  if (code.value) {
    loadKline()
    resolveStockName()
  }
})
</script>

<template>
  <AppPage title="行情" subtitle="市场全景与个股技术分析">
    <template #actions>
      <SearchInput
        v-model="code"
        width="260px"
        placeholder="搜索股票 / 代码"
        @select="onPick"
        @submit="onSubmit"
      />
    </template>

    <SectionCard :padded="false">
      <div style="padding: 0 var(--sp-5)">
        <PageToolbar v-model="tab" :tabs="TABS" />
      </div>

      <!-- 市场 -->
      <div v-if="tab === 'market'" class="pane">
        <LoadingBlock v-if="marketLoading && !indices.length" :rows="6" />
        <EmptyGuide v-else-if="marketError && !indices.length" icon="alert" title="市场数据加载失败" :desc="marketError">
          <template #action><button class="ui-btn" @click="loadMarket()">重试</button></template>
        </EmptyGuide>
        <template v-else>
          <div class="indices">
            <div v-for="idx in indices" :key="idx.code" class="index-card">
              <div class="index-card__name">{{ idx.name }}</div>
              <div class="index-card__price num">{{ idx.price.toLocaleString() }}</div>
              <div class="index-card__chg num" :class="idx.change_pct >= 0 ? 'up' : 'down'">
                {{ fmtPct(idx.change_pct) }}
              </div>
            </div>
          </div>

          <div class="market-cols">
            <div>
              <h3 class="sub-title">行业板块</h3>
              <DataTable
                :columns="sectorColumns"
                :rows="sectors.slice(0, 30)"
                row-key="name"
                storage-key="market-sectors"
                compact
                :page-size="0"
              >
                <template #cell-change_pct="{ row }">
                  <span :class="Number(row.change_pct) >= 0 ? 'up' : 'down'">
                    {{ fmtPct(Number(row.change_pct)) }}
                  </span>
                </template>
              </DataTable>
            </div>
            <div>
              <h3 class="sub-title">北向资金（历史，2024-08 后停更）</h3>
              <DataTable
                :columns="northColumns"
                :rows="north.slice(0, 15)"
                row-key="date"
                storage-key="market-kline"
                compact
                :page-size="0"
              >
                <template #cell-net_flow="{ row }">
                  <span :class="Number(row.net_flow) >= 0 ? 'up' : 'down'">
                    {{ fmtNum(Number(row.net_flow)) }}
                  </span>
                </template>
              </DataTable>
            </div>
          </div>
        </template>
      </div>

      <!-- 个股 -->
      <div v-else-if="tab === 'stock'" class="pane">
        <EmptyGuide
          v-if="!code && !kline.length && !minuteBars.length"
          icon="kline"
          title="搜索一只股票查看 K 线"
          desc="在右上角输入代码或名称，支持键盘上下选择。"
        />
        <LoadingBlock v-else-if="klineLoading && !kline.length && !minuteBars.length" :rows="8" />
        <EmptyGuide
          v-else-if="klineError && !kline.length && !minuteBars.length"
          icon="alert" title="K线加载失败" :desc="klineError"
        >
          <template #action><button class="ui-btn" @click="loadKline">重试</button></template>
        </EmptyGuide>
        <template v-else-if="kline.length || minuteBars.length">
          <div class="stock-head">
            <div>
              <span class="stock-head__name">{{ stockName || code }}</span>
              <span v-if="stockName && stockName !== code" class="stock-head__code num">{{ code }}</span>
              <span class="stock-head__adj">前复权</span>
            </div>
            <div class="stock-head__quote">
              <span class="stock-head__price num">{{ headQuote?.price.toFixed(2) }}</span>
              <span class="num" :class="changePct >= 0 ? 'up' : 'down'">{{ fmtPct(changePct) }}</span>
            </div>
          </div>

          <!-- 周期与指标工具条（券商式） -->
          <div class="kbar">
            <div class="kbar__row">
              <div class="kbar__periods">
                <button
                  v-for="p in PERIOD_OPTIONS" :key="p.value"
                  class="kbar__btn" :class="{ 'is-on': period === p.value }"
                  @click="period = p.value as Period"
                >{{ p.label }}</button>
              </div>
              <span class="kbar__spacer" />
              <span class="kbar__hint">1-9 周期 · ←→ 平移 · ↑↓ 缩放 · Home 复位 · 图表内点选后生效</span>
              <div v-if="!isMinute" class="kbar__days">
                <button
                  v-for="d in DAY_OPTIONS" :key="d.value"
                  class="kbar__btn kbar__btn--sm" :class="{ 'is-on': days === d.value }"
                  @click="days = d.value"
                >{{ d.label }}</button>
              </div>
            </div>
            <div class="kbar__row kbar__row--sub">
              <span class="kbar__lbl">主图</span>
              <button
                v-for="n in MA_CHOICES" :key="n"
                class="kbar__chip" :class="{ 'is-on': maSet.includes(n) }"
                @click="toggleMa(n)"
              >MA{{ n }}</button>
              <button class="kbar__chip" :class="{ 'is-on': bollOn }" @click="bollOn = !bollOn">BOLL</button>
              <button class="kbar__chip" :class="{ 'is-on': sarOn }" title="抛物线转向 SAR" @click="sarOn = !sarOn">SAR</button>
              <button class="kbar__chip" :class="{ 'is-on': chipOn }" title="筹码分布（平均成本 + 90% 成本区间）" @click="chipOn = !chipOn">筹码</button>
              <button
                v-if="!isMinute" class="kbar__chip kbar__chip--auto"
                :class="{ 'is-on': autoOn }" title="程序自动画线 + 结构解读"
                @click="autoOn = !autoOn"
              >程序画线</button>
              <span class="kbar__spacer" />
              <span class="kbar__lbl">副图</span>
              <button
                v-for="s in SUB_OPTIONS" :key="s.value"
                class="kbar__chip" :class="{ 'is-on': subIndicator === s.value }"
                @click="subIndicator = s.value as SubKind"
              >{{ s.label }}</button>
              <button
                v-if="subIndicator !== 'none'"
                class="kbar__chip kbar__chip--gear" :class="{ 'is-on': paramOpen }"
                title="指标参数" @click="paramOpen = !paramOpen"
              >参数</button>
            </div>
          </div>

          <KlineChart
            :bars="lwcBars"
            :height="470"
            :fund-flow="isMinute ? [] : lwcFundFlow"
            :show-fund-flow="!isMinute"
            :limit-pct="isMinute ? 0 : limitPct"
            :mas="maSet"
            :boll="bollOn"
            :sar="sarOn"
            :sub-params="curParams"
            :chips="chipOverlay"
            :chips-rows="cyqRows"
            :sub="subIndicator"
            :intraday="isMinute"
            :timeshare="isTimeshare"
            :prev-close="prevClose"
            :title="`${stockName || code} ${periodLabel}`"
            :analysis="autoOn ? analysis : null"
            @period-key="setPeriodByKey"
          />

          <!-- 指标参数弹层 -->
          <div v-if="paramOpen && subIndicator !== 'none'" class="param-pop">
            <div class="param-pop__head">
              <span>{{ SUB_SPECS[subIndicator].label }} 参数</span>
              <button class="ui-btn ui-btn--ghost" style="padding:2px 8px;font-size:11px" @click="resetParams">重置</button>
            </div>
            <div v-if="SUB_SPECS[subIndicator].help" class="param-pop__help">{{ SUB_SPECS[subIndicator].help }}</div>
            <div class="param-pop__body">
              <label v-for="p in SUB_SPECS[subIndicator].params" :key="p.key" class="param-pop__item">
                <span>{{ p.label }}</span>
                <input
                  type="number" min="1" step="1"
                  :value="curParams[p.key] ?? p.def"
                  @change="setParam(p.key, $event)"
                />
              </label>
            </div>
          </div>
          <div v-if="paramOpen" class="param-mask" @click="paramOpen = false" />

          <!-- 筹码分布卡片 -->
          <div v-if="chipOn && cyq" class="auto-card auto-card--chip">
            <div class="auto-card__head">
              <span class="auto-card__badge" style="background: var(--accent)">筹码分布</span>
              <span class="auto-card__route">
                获利盘 {{ (Number(cyq.profit_ratio) * 100).toFixed(1) }}%
                · 平均成本 {{ Number(cyq.avg_cost).toFixed(2) }}
              </span>
              <span class="auto-card__meta">as-of {{ cyq.date }} · 成本数据 250 日窗口</span>
            </div>
            <div class="auto-card__levels">
              <span class="auto-chip">90% 筹码 {{ Number(cyq.cost90_low).toFixed(2) }} ~ {{ Number(cyq.cost90_high).toFixed(2) }}<i>集中度 {{ (Number(cyq.conc90) * 100).toFixed(1) }}%</i></span>
              <span class="auto-chip">70% 筹码 {{ Number(cyq.cost70_low).toFixed(2) }} ~ {{ Number(cyq.cost70_high).toFixed(2) }}<i>集中度 {{ (Number(cyq.conc70) * 100).toFixed(1) }}%</i></span>
            </div>
            <div class="auto-card__disc">{{ chipNote }}。图中已标注平均成本与 90% 成本区间（黄色虚线 = 平均成本，灰点线 = 90% 区间）</div>
          </div>

          <!-- 程序自动分析卡片 -->
          <div v-if="autoOn && !isMinute && analysis?.ok" class="auto-card">
            <div class="auto-card__head">
              <span class="auto-card__badge">程序分析</span>
              <span class="auto-card__route">{{ (analysis.structure || {}).route || analysis.trend.label || '—' }}</span>
              <span class="auto-card__meta">
                ATR14 {{ analysis.atr14 }} · 收盘 {{ analysis.close }} · as-of {{ analysis.as_of }}
              </span>
            </div>
            <ul class="auto-card__notes">
              <li v-for="(n, i) in analysis.notes" :key="i">{{ n }}</li>
            </ul>
            <div class="auto-card__levels">
              <span v-for="lv in analysis.levels" :key="lv.label" class="auto-chip"
                    :class="lv.role === 'support' ? 'auto-chip--sup' : 'auto-chip--res'">
                {{ lv.label }}<i v-if="lv.dist_atr != null">{{ lv.dist_atr > 0 ? '+' : '' }}{{ lv.dist_atr }}×ATR</i>
              </span>
            </div>
            <div class="auto-card__disc">由确定性规则自动生成（摆动点/区间/突破质量与 AI 操盘手同源），不构成投资建议</div>
          </div>
          <div v-if="!isMinute" class="detail-table">
            <h3 class="sub-title">历史数据（近 {{ Math.min(kline.length, 60) }} 条）</h3>
            <DataTable
              :columns="klineColumns"
              :rows="klineRows.slice(0, 60)"
              row-key="date"
              compact
              :page-size="20"
            />
          </div>
        </template>
      </div>

      <!-- ETF -->
      <div v-else-if="tab === 'etf'" class="pane">
        <EtfPanel />
      </div>
    </SectionCard>
  </AppPage>
</template>

<style scoped>
.pane { padding: var(--sp-5); }
.indices {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  gap: var(--sp-3);
  margin-bottom: var(--sp-5);
}
.index-card {
  padding: var(--sp-4);
  background: linear-gradient(180deg, var(--bg-raised), var(--bg));
  border: 1px solid var(--border-soft);
  border-radius: var(--radius-md);
  box-shadow: inset 0 1px 0 var(--sheen);
  transition: border-color var(--dur-fast) var(--ease), transform var(--dur-fast) var(--ease),
    box-shadow var(--dur-fast) var(--ease);
}
.index-card:hover {
  border-color: var(--border-strong);
  transform: translateY(-2px);
  box-shadow: inset 0 1px 0 var(--sheen), var(--shadow-lift);
}
.index-card__name { font-size: var(--fs-sm); color: var(--text-sub); }
.index-card__price { font-size: var(--fs-xl); font-weight: 700; margin: 2px 0; }
.index-card__chg { font-size: var(--fs-md); font-weight: 500; }
.market-cols {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: var(--sp-5);
}
.quoted-sub-title-disabled {
  margin: 0 0 var(--sp-2);
  font-size: var(--fs-md);
  font-weight: 600;
  color: var(--text-sub);
}
.stock-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--sp-4);
  margin-bottom: var(--sp-3);
  flex-wrap: wrap;
}
.stock-head__name { font-size: var(--fs-xl); font-weight: 650; }
.stock-head__code { margin-left: var(--sp-2); color: var(--text-faint); font-size: var(--fs-sm); }
.stock-head__quote { display: flex; align-items: baseline; gap: var(--sp-3); }
.stock-head__price { font-size: var(--fs-2xl); font-weight: 700; }
.detail-table { margin-top: var(--sp-5); }

/* ---- 周期与指标工具条（券商式） ---- */
.stock-head__adj {
  margin-left: var(--sp-2);
  font-size: 11px;
  color: var(--text-faint);
  border: 1px solid var(--border-soft);
  border-radius: var(--radius-pill, 999px);
  padding: 1px 7px;
  vertical-align: 2px;
}
.kbar {
  border: 1px solid var(--border-soft);
  border-radius: var(--radius-md);
  background: var(--bg-raised);
  padding: 6px 8px;
  margin-bottom: var(--sp-3);
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.kbar__row { display: flex; align-items: center; gap: 4px; flex-wrap: wrap; }
.kbar__row--sub { border-top: 1px dashed var(--border); padding-top: 5px; }
.kbar__periods { display: flex; gap: 2px; flex-wrap: wrap; }
.kbar__spacer { flex: 1; }
.kbar__lbl { font-size: 11px; color: var(--text-faint); margin-right: 2px; }
.kbar__btn {
  padding: 3px 10px;
  font-size: 12px;
  border-radius: var(--radius-sm, 6px);
  border: 1px solid transparent;
  background: transparent;
  color: var(--text-sub);
  cursor: pointer;
  transition: color var(--dur-fast) var(--ease), background var(--dur-fast) var(--ease);
}
.kbar__btn:hover { color: var(--text); background: var(--bg-hover); }
.kbar__btn.is-on { color: var(--on-gold, #1a1d23); background: var(--gold); border-color: var(--gold); font-weight: 600; }
.kbar__btn--sm { padding: 2px 8px; font-size: 11px; }
.kbar__chip {
  padding: 2px 8px;
  font-size: 11px;
  border-radius: var(--radius-pill, 999px);
  border: 1px solid var(--border);
  background: transparent;
  color: var(--text-faint);
  cursor: pointer;
  transition: all var(--dur-fast) var(--ease);
}
.kbar__chip:hover { color: var(--text-sub); border-color: var(--border-strong); }
.kbar__chip.is-on { color: var(--accent); border-color: var(--accent); background: var(--accent-dim, transparent); }
.kbar__days { display: flex; gap: 2px; }
.kbar__hint { margin-left: 10px; font-size: 11px; color: var(--text-faint); }
.kbar__chip--auto.is-on { color: var(--gold); border-color: var(--gold); }
.kbar__chip--gear { border-style: dashed; }
.param-pop {
  position: absolute;
  right: 24px;
  top: 60px;
  z-index: 30;
  width: 240px;
  padding: 10px 12px;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-md);
  background: var(--bg-raised);
  box-shadow: var(--shadow-pop);
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.param-pop__head { display: flex; align-items: center; justify-content: space-between; font-size: 12px; font-weight: 600; color: var(--text); }
.param-pop__body { display: flex; flex-wrap: wrap; gap: 8px 12px; }
.param-pop__help { font-size: 11px; color: var(--text-sub); line-height: 1.6; border-bottom: 1px dashed var(--border); padding-bottom: 6px; }
.param-pop__item { display: flex; align-items: center; gap: 5px; font-size: 11px; color: var(--text-sub); }
.param-pop__item input {
  width: 52px;
  padding: 3px 6px;
  font-size: 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm, 6px);
  background: var(--bg-panel);
  color: var(--text);
}
.param-mask { position: fixed; inset: 0; z-index: 20; }

.auto-card {
  margin-top: var(--sp-3);
  padding: 12px 14px;
  border: 1px solid var(--border-soft);
  border-left: 3px solid var(--gold);
  border-radius: var(--radius-md);
  background: linear-gradient(180deg, var(--bg-raised), var(--bg-panel));
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.auto-card__head { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }
.auto-card__badge {
  font-size: 11px; font-weight: 700; color: var(--on-gold, #1a1d23);
  background: var(--gold); border-radius: var(--radius-pill, 999px); padding: 2px 8px;
}
.auto-card__route { font-size: var(--fs-md); font-weight: 650; color: var(--text); }
.auto-card__meta { font-size: 11px; color: var(--text-faint); margin-left: auto; }
.auto-card__notes { margin: 0; padding-left: 18px; display: flex; flex-direction: column; gap: 3px; }
.auto-card__notes li { font-size: var(--fs-sm); color: var(--text-sub); line-height: 1.6; }
.auto-card__levels { display: flex; flex-wrap: wrap; gap: 6px; }
.auto-chip {
  font-size: 11px; padding: 3px 9px; border-radius: var(--radius-pill, 999px);
  border: 1px solid var(--border); color: var(--text-sub);
}
.auto-chip i { font-style: normal; margin-left: 5px; color: var(--text-faint); }
.auto-chip--sup { border-color: color-mix(in srgb, var(--down) 45%, transparent); color: var(--down); }
.auto-chip--res { border-color: color-mix(in srgb, var(--up) 45%, transparent); color: var(--up); }
.auto-card__disc { font-size: 11px; color: var(--text-faint); }
</style>
