<script setup lang="ts">
/**
 * 基金套利（LOF 折溢价）
 * 两条腿：溢价（场外申购净值 → 场内卖出）/ 折价（场内买入 → 场外赎回）
 * 全部口径 = 收盘价 + 最新公布净值（同源日）；成本可调（佣金/申购费折扣/赎回费分档/滑点/占用天数）。
 */
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import AppPage from '@/components/ui/AppPage.vue'
import SectionCard from '@/components/ui/SectionCard.vue'
import StatTile from '@/components/ui/StatTile.vue'
import DataTable from '@/components/ui/DataTable.vue'
import Drawer from '@/components/ui/Drawer.vue'
import SegmentedControl from '@/components/ui/SegmentedControl.vue'
import EmptyGuide from '@/components/ui/EmptyGuide.vue'
import Icon from '@/components/Icon.vue'
import { usePersistedRef } from '@/composables/usePersistedRef'
import { useEChart, cssVar } from '@/composables/useEChart'
import { useJobsStore } from '@/stores/jobs'
import {
  getArbList, getArbDetail, getArbStats, syncArb,
  type ArbItem, type ArbDetail, type ArbPlan,
} from '@/api'

const jobs = useJobsStore()

/**
 * embedded：本视图已从独立页面（侧边导航「套利」）降级为**行情页的一个页内 Tab**。
 * 嵌入时不渲染自己的标题区，避免与外层页面标题重复、也省掉一层纵向空间。
 * 与 `Research/Optimize/Replay` 被 Strategy 嵌入时同款约定。
 *
 * 用 `props.embedded` 而非解构：模板里要持续跟踪该值。
 */
const props = withDefaults(defineProps<{ embedded?: boolean }>(), { embedded: false })

// ---------------- 过滤 & 成本参数（持久化） ----------------
const direction = usePersistedRef<string>('arb.direction', 'all')
const minSpace = usePersistedRef<number>('arb.minSpace', 0)
const onlyOpen = usePersistedRef<boolean>('arb.onlyOpen', false)
const showCfg = ref(false)
/** 全部机会明细（大表）：平时折叠，只作一个功能块 */
const showTable = usePersistedRef<boolean>('arb.showTable', false)

interface Cfg { amount: number; commission_rate: number; commission_min: number; buy_fee_discount: number; transfer_fee: number; slippage_ticks: number; premium_days: number; discount_days: number }
const DEFAULT_CFG: Cfg = {
  amount: 10000, commission_rate: 0.00025, commission_min: 5,
  buy_fee_discount: 1, transfer_fee: 0, slippage_ticks: 1, premium_days: 3, discount_days: 3,
}
const cfg = usePersistedRef<Cfg>('arb.cfg', { ...DEFAULT_CFG })
function resetCfg() { cfg.value = { ...DEFAULT_CFG } }

const cfgParams = computed(() => ({
  amount: cfg.value.amount,
  commission_rate: cfg.value.commission_rate,
  commission_min: cfg.value.commission_min,
  buy_fee_discount: cfg.value.buy_fee_discount,
  transfer_fee: cfg.value.transfer_fee,
  slippage_ticks: cfg.value.slippage_ticks,
  premium_days: cfg.value.premium_days,
  discount_days: cfg.value.discount_days,
}))

// ---------------- 列表 ----------------
const rows = ref<ArbItem[]>([])
const total = ref(0)
const loading = ref(false)
const stats = ref<Record<string, unknown> | null>(null)
const lastLoaded = ref('')

async function load() {
  loading.value = true
  try {
    const r = await getArbList({
      direction: direction.value === 'all' ? undefined : direction.value,
      min_space: minSpace.value,
      only_open: onlyOpen.value ? 1 : undefined,
      limit: 500,
      ...cfgParams.value,
    })
    rows.value = r.items
    total.value = r.total
    lastLoaded.value = new Date().toLocaleTimeString('zh-CN', { hour12: false })
  } finally {
    loading.value = false
  }
}
async function loadStats() {
  try { stats.value = await getArbStats() } catch { /* 忽略 */ }
}

onMounted(() => { load(); loadOpps(); loadStats() })
watch([direction, minSpace, onlyOpen], load)

// ---------------- 可执行机会面板（主区域） ----------------
const oppsTotal = ref(0)
const oppsLoading = ref(false)
/** 口径：扣费后净空间 > 0 且 申购/赎回开放 且 成交额 ≥ 50 万（能真正做得了的那部分） */
const oppsRaw = ref<ArbItem[]>([])
async function loadOpps() {
  oppsLoading.value = true
  try {
    const r = await getArbList({
      min_space: 0, executable_only: 1, liquid_only: 1, limit: 200, ...cfgParams.value,
    })
    oppsRaw.value = r.items
    oppsTotal.value = r.total
  } catch {
    oppsRaw.value = []
  } finally {
    oppsLoading.value = false
  }
}
/** 面板阈值：净空间低于此值视为「空间太薄」，不值得动手 */
const panelMinSpace = usePersistedRef<number>('arb.panelMinSpace', 0.5)
/** 面板显示：可执行 + 本金窗口够用 + 空间不薄 */
const opps = computed(() => oppsRaw.value.filter(
  (o) => windowState(o) === 'ok' && o.space_pct >= panelMinSpace.value,
))
/** 被面板过滤掉的（可执行但窗口窄/空间薄） */
const oppsExcluded = computed(() => oppsRaw.value.filter(
  (o) => !(windowState(o) === 'ok' && o.space_pct >= panelMinSpace.value),
))
/** 另有：算术有空间但不可执行/流动性不足的数量 */
const oppsHidden = computed(() => Math.max(0, total.value - oppsTotal.value))

const counts = computed(() => {
  const prem = rows.value.filter((r) => r.direction === 'premium')
  const disc = rows.value.filter((r) => r.direction === 'discount')
  return {
    prem: prem.length, disc: disc.length,
    premProfitable: prem.filter((r) => (planOf(r)?.space_pct ?? -1) > 0).length,
    discProfitable: disc.filter((r) => (planOf(r)?.space_pct ?? -1) > 0).length,
    maxSpace: rows.value.reduce((m, r) => Math.max(m, planOf(r)?.space_pct ?? -9), -9),
  }
})
/** 数据日期 = 各行「价格/净值对齐日」的最大值（净值未公布时自动回退，不是错配口径） */
const dataDate = computed(() => rows.value.reduce((m, r) => (r.price_date && r.price_date > m ? r.price_date : m), '')
  || (stats.value?.daily_last as string) || '—')
/** 有多少只还在等当日净值（全量口径，来自后端 stats） */
const lagging = computed(() => Number(stats.value?.nav_lagging ?? 0))

// ---------------- 同步数据 ----------------
const syncing = computed(() => jobs.activeByKind('fund_arb') !== null)
async function sync(mode: 'daily' | 'fees' = 'daily') {
  await jobs.run({
    kind: 'fund_arb',
    title: mode === 'daily' ? '套利数据同步（日更）' : '套利费率刷新',
    route: 'fundarb',
    submit: async () => {
      const r = await syncArb(mode)
      return { job_id: r.job.job_id }
    },
  })
}
watch(
  () => jobs.byKind('fund_arb').map((j) => j.doneTick ?? 0).join(','),
  () => { if (!syncing.value) { load(); loadOpps(); loadStats() } },
)

// ---------------- 明细抽屉 ----------------
const detailOpen = ref(false)
const detail = ref<ArbDetail | null>(null)
const detailLoading = ref(false)
/** 试算：本金 + 腿（点开某只时自动切到该只的方向） */
const calcAmount = usePersistedRef<number>('arb.calcAmount', 10000)
const calcLeg = ref<'premium' | 'discount'>('premium')
let calcTimer: ReturnType<typeof setTimeout> | null = null

async function refreshDetail(code?: string) {
  const c = code || detail.value?.code
  if (!c) return
  detail.value = await getArbDetail(c, { ...cfgParams.value, amount: calcAmount.value, hist_days: histDays.value })
  await nextTick()
  drawDetail()
  drawCurve()
}

// ---- 本金-收益曲线 ----
const curveChartEl = ref<HTMLElement | null>(null)
const { draw: drawCurve } = useEChart(curveChartEl, () => {
  const pts = (detail.value?.curve?.[calcLeg.value] ?? []) as {
    amount: number; profit: number; space_pct: number; fee_pct: number
  }[]
  if (!pts.length) return {}
  const be = calcPlan.value?.breakeven ?? null
  const cap = detail.value?.max_amount ?? null
  const marks: Record<string, unknown>[] = []
  if (be) marks.push({ xAxis: be, name: '保本', lineStyle: { color: cssVar('--up', '#d08770'), type: 'dashed' } })
  if (cap) marks.push({ xAxis: cap, name: '上限', lineStyle: { color: cssVar('--down', '#8fbc8f'), type: 'dashed' } })
  const cur = Number(calcAmount.value)
  const near = pts.reduce((b, p) => (Math.abs(p.amount - cur) < Math.abs(b.amount - cur) ? p : b), pts[0])
  const fmt = (v: number) => (v >= 10000 ? `${(v / 10000).toFixed(0)}万` : `${Math.round(v)}`)
  return {
    grid: { left: 4, right: 10, top: 30, bottom: 18, containLabel: true },
    legend: { top: 0, itemWidth: 12, itemHeight: 8, textStyle: { fontSize: 10 } },
    tooltip: {
      trigger: 'axis',
      valueFormatter: (v: unknown) => String(v),
      formatter: (ps: unknown) => {
        const arr = ps as { dataIndex?: number }[]
        const p = pts[arr?.[0]?.dataIndex ?? 0]
        if (!p) return ''
        return `本金 ${Math.round(p.amount).toLocaleString()} 元<br/>净赚 <b>${p.profit.toFixed(1)}</b> 元`
          + `<br/>收益率 ${p.space_pct.toFixed(3)}% · 费用占比 ${p.fee_pct.toFixed(2)}%`
      },
    },
    xAxis: {
      type: 'log', name: '本金(元)', nameTextStyle: { fontSize: 10 },
      axisLabel: { fontSize: 10, formatter: (v: number) => fmt(v) },
      splitLine: { lineStyle: { opacity: 0.15 } },
    },
    yAxis: [
      { type: 'value', name: '净赚(元)', nameTextStyle: { fontSize: 10 }, axisLabel: { fontSize: 10 },
        splitLine: { lineStyle: { opacity: 0.2 } } },
      { type: 'value', name: '收益率(%)', nameTextStyle: { fontSize: 10 }, axisLabel: { fontSize: 10, formatter: '{value}%' },
        splitLine: { show: false } },
    ],
    series: [
      {
        name: '净赚(元)', type: 'line', data: pts.map((p) => [p.amount, p.profit]), showSymbol: false,
        lineStyle: { width: 2, color: cssVar('--accent', '#d4a574') }, itemStyle: { color: cssVar('--accent', '#d4a574') },
        areaStyle: { opacity: 0.10, color: cssVar('--accent', '#d4a574') },
        markLine: { silent: true, symbol: 'none', label: { fontSize: 9 }, data: marks },
      },
      {
        name: '收益率(%)', type: 'line', yAxisIndex: 1, data: pts.map((p) => [p.amount, p.space_pct]),
        showSymbol: false, lineStyle: { width: 1, type: 'dashed', color: cssVar('--gold', '#c0a062') },
        itemStyle: { color: cssVar('--gold', '#c0a062') },
      },
      {
        name: '当前本金', type: 'scatter', data: [[near.amount, near.profit]], symbolSize: 9,
        itemStyle: { color: cssVar('--accent', '#d4a574'), borderColor: '#fff', borderWidth: 1 },
      },
    ],
  }
})
const detailChartEl = ref<HTMLElement | null>(null)
const histDays = usePersistedRef<number>('arb.histDays', 250)

const { draw: drawDetail } = useEChart(detailChartEl, () => {
  const h = detail.value?.history ?? []
  return {
    grid: { left: 8, right: 12, top: 18, bottom: 24, containLabel: true },
    tooltip: {
      trigger: 'axis',
      valueFormatter: (v: unknown) => `${Number(v).toFixed(3)}%`,
    },
    xAxis: { type: 'category', data: h.map((x) => x.date), axisLabel: { fontSize: 10 } },
    yAxis: { type: 'value', axisLabel: { formatter: '{value}%', fontSize: 10 }, splitLine: { lineStyle: { opacity: 0.25 } } },
    series: [{
      type: 'line', data: h.map((x) => x.premium_pct), showSymbol: false, lineStyle: { width: 1.5 },
      areaStyle: { opacity: 0.12 },
      markLine: { silent: true, symbol: 'none', data: [{ yAxis: 0 }], lineStyle: { type: 'dashed', opacity: 0.6 } },
    }],
  }
})

async function openDetail(item: ArbItem) {
  detailOpen.value = true
  detailLoading.value = true
  calcLeg.value = item.direction === 'discount' ? 'discount' : 'premium'
  try {
    detail.value = await getArbDetail(item.code, { ...cfgParams.value, amount: calcAmount.value, hist_days: histDays.value })
    detailLoading.value = false   // 先切到详情分支，图表容器才会挂载
    await nextTick()
    drawDetail()
    drawCurve()
  } catch {
    detailLoading.value = false
  }
}

/** 试算输入变化（防抖 300ms）后重算 */
function onCalcInput() {
  if (calcTimer) clearTimeout(calcTimer)
  calcTimer = setTimeout(() => { void refreshDetail() }, 300)
}
watch(histDays, () => { if (detail.value) void refreshDetail() })
watch(calcLeg, async () => { await nextTick(); drawCurve() })
watch([() => cfg.value.amount, () => cfg.value.commission_rate, () => cfg.value.buy_fee_discount, calcAmount], () => {
  if (detail.value && detailOpen.value) void refreshDetail()
})

/** 试算结果（当前腿） */
const calcPlan = computed(() => {
  if (!detail.value) return null
  return calcLeg.value === 'premium' ? (detail.value.plans.premium ?? null) : (detail.value.plans.discount ?? null)
})
/** 试算提示：保本金额 / 本金上限 */
const calcHint = computed(() => {
  const p = calcPlan.value
  if (!p || !detail.value) return ''
  const msgs: string[] = []
  if (p.breakeven && calcAmount.value < p.breakeven) {
    msgs.push(`低于保本金额 ${yuan(p.breakeven, 0)} 元：手续费吃掉空间，这笔是亏的`)
  }
  if (detail.value.max_amount && calcAmount.value > detail.value.max_amount) {
    msgs.push(`超过本金上限 ${yuan(detail.value.max_amount, 0)} 元（日限额 / 成交额×10%），超出部分要承担冲击成本`)
  }
  return msgs.join('；')
})

// ---------------- 格式化 ----------------
function planOf(r: ArbItem): ArbPlan | null {
  return r.direction === 'premium' ? r.premium : r.discount
}
function pct(v: unknown, digits = 3): string {
  const n = Number(v)
  if (!Number.isFinite(n)) return '—'
  if (Math.abs(n) >= 999) return `${n >= 0 ? '+' : '-'}999%+`
  return `${n >= 0 ? '+' : ''}${n.toFixed(digits)}%`
}
function pctPlain(v: unknown, digits = 3): string {
  const n = Number(v)
  return Number.isFinite(n) ? `${n.toFixed(digits)}%` : '—'
}
function yuan(v: unknown, digits = 1): string {
  const n = Number(v)
  return Number.isFinite(n) ? `${n.toFixed(digits)}` : '—'
}
function money(v: unknown): string {
  const n = Number(v)
  if (!Number.isFinite(n) || n === 0) return '—'
  if (n >= 1e8) return `${(n / 1e8).toFixed(2)}亿`
  if (n >= 1e4) return `${(n / 1e4).toFixed(0)}万`
  return `${n.toFixed(0)}`
}
function amountText(v: unknown): string {
  const n = Number(v)
  if (!Number.isFinite(n) || n <= 0) return '—'
  if (n >= 1e8) return `${(n / 1e8).toFixed(1)}亿`
  if (n < 1e4) return `${Math.round(n)}元`
  return `${Math.round(n / 1e4)}万`
}
function limitText(v: unknown): string {
  const n = Number(v)
  if (!Number.isFinite(n) || n <= 0 || n >= 1e10) return '无限额'
  if (n >= 1e8) return `${(n / 1e8).toFixed(0)}亿`
  if (n < 1e4) return `${Math.round(n)}元`
  return `${Math.round(n / 1e4)}万`
}
/** 面板行 hover 提示：把明细放进 tooltip，不占版面 */
function oppTitle(o: ArbItem): string {
  const p = planOf(o)
  return [
    `${o.direction === 'premium' ? '溢价套利' : '折价套利'} · 净空间 ${pct(o.space_pct)}（已扣费）`,
    `每万元 ${yuan(o.profit_per_10k)} 元 · 占用 ${p?.days} 天 · 成交额 ${amountText(o.amount)}`,
    `保本本金 ${p?.breakeven ? yuan(p.breakeven, 0) + ' 元' : '—'} · 本金上限 ${o.max_amount ? yuan(o.max_amount, 0) + ' 元' : '无明确上限'}`,
    o.min_amount ? `起点 ${yuan(o.min_amount, 0)} 元` : '',
    o.daily_limit && o.daily_limit < 1e10 ? `日限额 ${limitText(o.daily_limit)}` : '',
    o.tags.length ? `标签：${o.tags.join('、')}` : '',
    '点击查看成本拆解 / 历史实测',
  ].filter(Boolean).join('\n')
}
function sign(v: unknown): string {
  const n = Number(v)
  return Number.isFinite(n) ? (n > 0 ? 'up' : n < 0 ? 'down' : '') : ''
}
function statusText(v: unknown): string {
  const s = String(v ?? '')
  if (!s) return '—'
  return s.replace('开放申购', '开放').replace('开放赎回', '开放')
}
function num(v: unknown, d = 4): number { const n = Number(v); return Number.isFinite(n) ? n : 0 }
/** 本金窗口：ok=够用 / narrow=窄（上限不到保本的 1.5 倍）/ none=做不出利润 */
function windowState(o: ArbItem): 'ok' | 'narrow' | 'none' {
  const be = planOf(o)?.breakeven
  if (!be) return 'none'
  if (!o.max_amount) return 'ok'
  return be * 1.5 <= o.max_amount ? 'ok' : 'narrow'
}
/** 建议本金区间（窗口可用时：保本 ~ 上限取一个整数档） */
function sizeRange(o: ArbItem): string {
  const be = planOf(o)?.breakeven
  if (!be) return '—'
  const up = o.max_amount
  const upper = up ? Math.floor(up / 1000) * 1000 : null
  return upper && upper > be ? `${Math.round(be)}~${upper.toLocaleString()} 元` : `${Math.round(be)} 元起`
}

const columns = [
  { key: 'code', title: '代码', width: '72px' },
  {
    key: 'name', title: '名称', width: '150px', sortable: true,
    format: (r: Record<string, unknown>) => String(r.name ?? ''),
  },
  {
    key: 'direction', title: '方向', width: '66px', align: 'center' as const,
    format: (r: Record<string, unknown>) => (r.direction === 'premium' ? '溢价' : '折价'),
  },
  { key: 'price', title: '场内价', width: '76px', align: 'right' as const, sortable: true },
  { key: 'nav', title: '净值', width: '76px', align: 'right' as const, sortable: true },
  { key: 'premium_pct', title: '折溢价率', width: '92px', align: 'right' as const, sortable: true },
  { key: 'space_pct', title: '净空间', width: '92px', align: 'right' as const, sortable: true },
  { key: 'profit_per_10k', title: '每万元', width: '84px', align: 'right' as const, sortable: true },
  { key: 'annual_pct', title: '年化(折)', width: '88px', align: 'right' as const, sortable: true },
  { key: 'fee_pct', title: '费用', width: '80px', align: 'right' as const, sortable: true },
  { key: 'days', title: '占用', width: '62px', align: 'right' as const },
  { key: 'breakeven', title: '最小本金', width: '84px', align: 'right' as const, sortable: true },
  { key: 'amount', title: '成交额', width: '84px', align: 'right' as const, sortable: true },
  { key: 'purchase_status', title: '申购', width: '76px' },
  { key: 'min_amount', title: '起点', width: '72px', align: 'right' as const },
  { key: 'tags', title: '标签', width: '150px' },
]
</script>

<template>
  <AppPage
    title="基金套利"
    subtitle="LOF 折溢价：场内价 vs 单位净值，扣申购/赎回/佣金/转托管/滑点后的净空间"
    :embedded="props.embedded"
    actions-inline
  >
    <template #actions>
      <div class="arb-actions">
        <span class="arb-date">
          数据：{{ dataDate }}（价格/净值对齐）<template v-if="lagging"> · <em class="arb-lag">{{ lagging }} 只当日净值未公布，已回退</em></template>
          <template v-if="lastLoaded"> · 刷新 {{ lastLoaded }}</template>
        </span>
        <button class="arb-btn" :disabled="syncing" @click="sync('daily')">
          <Icon name="refresh" :size="14" />{{ syncing ? '同步中…' : '同步数据' }}
        </button>
        <button class="arb-btn arb-btn--ghost" :disabled="syncing" @click="sync('fees')">刷新费率</button>
        <button class="arb-btn arb-btn--ghost" @click="showCfg = !showCfg">
          <Icon name="settings" :size="14" />成本参数
        </button>
      </div>
    </template>

    <!-- 总览（常显） -->
    <div class="arb-tiles">
      <StatTile label="溢价机会（扣费后为正）" :value="counts.premProfitable" unit="只" :hint="`共 ${counts.prem} 只溢价`" trend="up" />
      <StatTile label="折价机会（扣费后为正）" :value="counts.discProfitable" unit="只" :hint="`共 ${counts.disc} 只折价`" trend="down" />
      <StatTile label="最大净空间" :value="Number.isFinite(counts.maxSpace) && counts.maxSpace > -9 ? counts.maxSpace.toFixed(3) : '—'" unit="%" hint="已扣全部费用" />
      <StatTile label="覆盖 LOF" :value="Number(stats?.lof_count ?? 0)" unit="只" :hint="`净值 ${Number(stats?.nav_rows ?? 0).toLocaleString()} 条`" />
    </div>

    <!-- 主区域：可执行机会 -->
    <SectionCard
      title="可执行机会"
      desc="申购/赎回开放 · 成交额 ≥ 50 万 · 净空间 ≥ 阈值 · 本金窗口够用；净空间为 T 日快照，历史实现见明细"
    >
      <template #actions>
        <span class="arb-panelctl">
          净空间 ≥
          <input v-model.number="panelMinSpace" type="number" step="0.1" min="0" />%
        </span>
        <span class="arb-count">共 {{ opps.length }} 只</span>
      </template>
      <div v-if="oppsLoading" class="arb-loading">加载中…</div>
      <div v-else-if="opps.length" class="arb-opps">
        <button v-for="o in opps" :key="o.code" class="arb-opp" :title="oppTitle(o)" @click="openDetail(o)">
          <span class="arb-opp__dir" :class="o.direction === 'premium' ? 'up' : 'down'">
            {{ o.direction === 'premium' ? '溢价' : '折价' }}
          </span>
          <span class="arb-opp__name">{{ o.name }}</span>
          <span class="arb-opp__code">{{ o.code }}</span>
          <span class="arb-opp__space" :class="sign(o.space_pct)">{{ pct(o.space_pct) }}</span>
          <span class="arb-opp__window">可做 {{ sizeRange(o) }}</span>
        </button>
      </div>
      <EmptyGuide
        v-else
        icon="info"
        title="今日没有值得动手的套利机会"
        :desc="`可执行的有 ${oppsTotal} 只，但都不满足「本金窗口够用 + 空间 ≥ ${panelMinSpace}%」；另有 ${oppsHidden} 只卡在暂停申购 / 限大额 / 流动性不足。展开下方「全部机会明细」可逐只核对。也可能是今天数据还没同步。`"
      />
      <div v-if="opps.length && oppsExcluded.length" class="arb-excluded">
        另有 {{ oppsExcluded.length }} 只可执行但被过滤：{{ oppsExcluded.slice(0, 6).map((o) => `${o.name}(${pct(o.space_pct)})`).join('、') }}{{ oppsExcluded.length > 6 ? ' 等' : '' }}
      </div>
    </SectionCard>

    <SectionCard v-if="showCfg" title="成本参数" desc="改这里 = 改全站口径：机会表与明细都会按这套参数重算">
      <div class="cfg-grid">
        <label class="cfg-item"><span>投入金额（元）</span><input v-model.number="cfg.amount" type="number" step="1000" min="100" /></label>
        <label class="cfg-item"><span>场内佣金率（万分之）</span><input v-model.number="cfg.commission_rate" type="number" step="0.05" min="0" /></label>
        <label class="cfg-item"><span>最低佣金（元）</span><input v-model.number="cfg.commission_min" type="number" step="1" min="0" /></label>
        <label class="cfg-item"><span>申购费折扣</span><input v-model.number="cfg.buy_fee_discount" type="number" step="0.1" min="0" max="1" /></label>
        <label class="cfg-item"><span>转托管费（元）</span><input v-model.number="cfg.transfer_fee" type="number" step="1" min="0" /></label>
        <label class="cfg-item"><span>卖出滑点（跳）</span><input v-model.number="cfg.slippage_ticks" type="number" step="1" min="0" /></label>
        <label class="cfg-item"><span>溢价占用（天）</span><input v-model.number="cfg.premium_days" type="number" step="1" min="1" /></label>
        <label class="cfg-item"><span>折价占用（天）</span><input v-model.number="cfg.discount_days" type="number" step="1" min="1" /></label>
      </div>
      <div class="cfg-tip">
        默认：佣金万 2.5（最低 5 元）、申购费不折（场外按公布费率，折扣 0.1 = 1 折）、转托管 0 元、卖出滑点 1 跳（0.001 元）、基金免印花税。
        <button class="arb-btn arb-btn--mini" @click="resetCfg">恢复默认</button>
      </div>
    </SectionCard>

    <!-- 全部机会明细（大表）：折叠功能块 -->
    <section class="arb-ov" :class="{ 'is-open': showTable }">
      <button class="arb-ov__head" @click="showTable = !showTable">
        <Icon :name="showTable ? 'chevron-down' : 'chevron-right'" :size="16" />
        <b>全部机会明细</b>
        <span class="arb-ov__sum">按净空间排序的全量列表（含暂停申购 / 流动性不足） · 共 {{ total }} 只</span>
        <span class="arb-ov__hint">{{ showTable ? '收起' : '展开' }}</span>
      </button>
      <div v-if="showTable" class="arb-ov__body">
      <div class="arb-filters">
        <SegmentedControl v-model="direction" size="sm" :options="[
          { value: 'all', label: '全部' }, { value: 'premium', label: '溢价' }, { value: 'discount', label: '折价' },
        ]" />
        <label class="arb-check">
          <input v-model="onlyOpen" type="checkbox" />仅开放申购
        </label>
        <label class="arb-min">
          最小净空间
          <input v-model.number="minSpace" type="number" step="0.1" />%
        </label>
        <span class="arb-sub">默认只看扣费后仍为正的机会（把上方改成负数可看全部）</span>
        <span class="arb-count">共 {{ total }} 只<template v-if="total > rows.length">（显示前 {{ rows.length }}）</template></span>
      </div>

      <DataTable
        :rows="rows as unknown as Record<string, unknown>[]"
        :columns="columns"
        storage-key="arb-list"
        row-key="code"
        :loading="loading"
        empty-title="没有符合条件的 LOF"
        empty-desc="试试放宽最小净空间，或点右上角「同步数据」拉取最新净值"
        @row-click="(r: Record<string, unknown>) => openDetail(r as unknown as ArbItem)"
      >
        <template #cell-name="{ row }">
          <span class="arb-name">{{ row.name }}</span>
        </template>
        <template #cell-price="{ row }">{{ num(row.price, 3) }}</template>
        <template #cell-nav="{ row }">{{ num(row.nav, 4) }}</template>
        <template #cell-premium_pct="{ row }">
          <span :class="sign(row.premium_pct)">{{ pct(row.premium_pct) }}</span>
        </template>
        <template #cell-space_pct="{ row }">
          <b :class="sign((row as unknown as ArbItem).space_pct)">{{ pct((row as unknown as ArbItem).space_pct) }}</b>
        </template>
        <template #cell-profit_per_10k="{ row }">
          <span :class="sign((row as unknown as ArbItem).profit_per_10k)">{{ yuan((row as unknown as ArbItem).profit_per_10k) }}</span>
        </template>
        <template #cell-annual_pct="{ row }">
          <span :class="sign(planOf(row as unknown as ArbItem)?.annual_pct)">{{ pct(planOf(row as unknown as ArbItem)?.annual_pct) }}</span>
        </template>
        <template #cell-fee_pct="{ row }">{{ pctPlain(planOf(row as unknown as ArbItem)?.fee_pct, 2) }}</template>
        <template #cell-days="{ row }">{{ planOf(row as unknown as ArbItem)?.days }} 天</template>
        <template #cell-breakeven="{ row }">
          <span>{{ planOf(row as unknown as ArbItem)?.breakeven ? yuan(planOf(row as unknown as ArbItem)?.breakeven, 0) : '—' }}</span>
        </template>
        <template #cell-amount="{ row }">
          <span :class="{ 'arb-weak': !(row as unknown as ArbItem).liquidity_ok }">{{ amountText(row.amount) }}</span>
        </template>
        <template #cell-purchase_status="{ row }">
          <span :class="{ 'arb-suspend': String(row.purchase_status ?? '').includes('暂停') }">{{ statusText(row.purchase_status) }}</span>
        </template>
        <template #cell-min_amount="{ row }">{{ (row as unknown as ArbItem).min_amount ? yuan((row as unknown as ArbItem).min_amount, 0) : '—' }}</template>
        <template #cell-tags="{ row }">
          <span v-for="t in ((row as unknown as ArbItem).tags || [])" :key="t" class="arb-tag">{{ t }}</span>
        </template>
      </DataTable>

      <div class="arb-note">
        口径：折溢价率 = 场内收盘价 ÷ 单位净值 − 1（同一净值日）；「净空间」= 扣掉申购费/赎回费/佣金/转托管/滑点后
        相对本金的收益率；年化按资金占用天数折算（不是承诺收益）。溢价套利要承担 T+2~T+3 内溢价消失的风险，
        折价套利要承担净值波动 + 赎回费（7 天内通常 1.5%）。
      </div>
      </div>
    </section>

    <Drawer :open="detailOpen" :title="detail ? `${detail.name}（${detail.code}）` : '加载中…'"
            :desc="detail ? `${detail.ftype ?? ''} · ${detail.exchange.toUpperCase()}` : ''"
            :width="620" @update:open="detailOpen = $event">
      <div v-if="detailLoading" class="arb-loading">加载中…</div>
      <template v-else-if="detail">
        <div class="arb-d-head">
          <div class="arb-d-big">
            <span class="arb-d-label">折溢价率</span>
            <span class="arb-d-value" :class="sign(detail.premium_pct)">{{ pct(detail.premium_pct) }}</span>
          </div>
          <div class="arb-d-meta">
            <div>场内价 <b>{{ num(detail.price, 3) }}</b>（{{ detail.price_date }}）</div>
            <div>单位净值 <b>{{ num(detail.nav, 4) }}</b>（{{ detail.nav_date }}）</div>
            <div>场内成交额 <b>{{ amountText(detail.amount) }}</b></div>
          </div>
          <div class="arb-d-tags">
            <span v-if="detail.purchase_status" class="arb-tag">{{ detail.purchase_status }}</span>
            <span v-if="detail.redeem_status" class="arb-tag">{{ detail.redeem_status }}</span>
            <span v-if="detail.min_amount" class="arb-tag">起点 {{ yuan(detail.min_amount, 0) }} 元</span>
            <span v-if="detail.daily_limit && detail.daily_limit < 1e10" class="arb-tag">日限 {{ limitText(detail.daily_limit) }}</span>
          </div>
        </div>

        <!-- 试算器：输入本金 → 份额 / 费用 / 净赚 -->
        <div class="arb-calc">
          <div class="arb-calc__head">
            <b>试算</b>
            <div class="arb-calc__ctl">
              <span>本金</span>
              <input v-model.number="calcAmount" type="number" step="500" min="100" @input="onCalcInput" @change="onCalcInput" />
              <span>元</span>
              <SegmentedControl v-model="calcLeg" size="sm" :options="[
                { value: 'premium', label: '溢价腿' }, { value: 'discount', label: '折价腿' },
              ]" />
            </div>
          </div>
          <template v-if="calcPlan">
            <div class="arb-calc__rows">
              <div>
                <span>{{ calcLeg === 'premium' ? '申购份额' : '买入份额' }}</span>
                <i>{{ Math.round(calcPlan.shares).toLocaleString() }} 份
                  <em>（{{ calcLeg === 'premium' ? '按净值 ' + num(detail.nav, 4) + ' 申购' : '按场内价 ' + num(detail.price, 3) + ' 买入' }}）</em>
                </i>
              </div>
              <div v-if="calcPlan.buy_fee !== undefined"><span>申购费</span><i>{{ yuan(calcPlan.buy_fee, 2) }} 元</i></div>
              <div><span>场内佣金</span><i>{{ yuan(calcPlan.commission, 2) }} 元</i></div>
              <div v-if="calcPlan.slippage_cost"><span>卖出滑点</span><i>{{ yuan(calcPlan.slippage_cost, 2) }} 元</i></div>
              <div v-if="calcPlan.redeem_fee !== undefined"><span>赎回费</span><i>{{ yuan(calcPlan.redeem_fee, 2) }} 元（{{ pctPlain(calcPlan.redeem_rate_pct, 2) }}）</i></div>
              <div><span>费用合计</span><i>{{ yuan(calcPlan.costs, 2) }} 元（占本金 {{ pctPlain(calcPlan.fee_pct, 2) }}）</i></div>
            </div>
            <div class="arb-calc__result">
              <span class="arb-calc__label">{{ calcLeg === 'premium' ? '申购→卖出' : '买入→赎回' }}净赚</span>
              <span class="arb-calc__value" :class="sign(calcPlan.profit)">{{ yuan(calcPlan.profit, 1) }} 元</span>
              <span class="arb-calc__sub">
                收益率 <b :class="sign(calcPlan.space_pct)">{{ pct(calcPlan.space_pct) }}</b>
                · 占用 {{ calcPlan.days }} 天
                · 折算年化 <b :class="sign(calcPlan.annual_pct)">{{ pct(calcPlan.annual_pct) }}</b>
              </span>
            </div>
            <div ref="curveChartEl" class="arb-curve" />
            <div v-if="calcHint" class="arb-calc__hint">{{ calcHint }}</div>
            <div class="arb-calc__other">
              换成另一条腿：<b :class="sign(calcLeg === 'premium' ? detail.plans.discount?.profit : detail.plans.premium?.profit)">
                {{ yuan(calcLeg === 'premium' ? detail.plans.discount?.profit : detail.plans.premium?.profit, 1) }} 元
              </b>
              <span class="arb-calc__note">（保本本金 {{ calcPlan.breakeven ? yuan(calcPlan.breakeven, 0) + ' 元' : '—' }}）</span>
            </div>
          </template>
          <div v-else class="arb-muted">该腿没有可用价格/净值，无法试算</div>
        </div>

        <!-- 本金与盈亏 -->
        <div v-if="detail.sizing && detail.sizing.length" class="arb-sec">
          <div class="arb-sec__head">
            <b>本金与盈亏</b>
            <span class="arb-sec__sub">佣金有 5 元最低值 → 本金越小、费用占比越高</span>
          </div>
          <table class="arb-table">
            <thead>
              <tr>
                <th>申购金额</th><th class="r">溢价腿净赚</th><th class="r">收益率</th>
                <th class="r">费用占比</th><th class="r">折价腿净赚</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="sg in detail.sizing" :key="sg.amount">
                <td>{{ sg.amount.toLocaleString() }} 元</td>
                <td class="r" :class="sign(sg.premium.profit)">{{ yuan(sg.premium.profit) }} 元</td>
                <td class="r" :class="sign(sg.premium.space_pct)">{{ pct(sg.premium.space_pct) }}</td>
                <td class="r">{{ pctPlain(sg.premium.fee_pct, 2) }}</td>
                <td class="r" :class="sign(sg.discount.profit)">{{ yuan(sg.discount.profit) }} 元</td>
              </tr>
            </tbody>
          </table>
          <div class="arb-warn" style="margin-top:8px">
            保本金额（覆盖手续费的最低申购金额）：
            <b>溢价腿 {{ detail.plans.premium?.breakeven ? yuan(detail.plans.premium?.breakeven, 0) + ' 元' : '无论多少都不赚' }}</b>；
            折价腿 {{ detail.plans.discount?.breakeven ? yuan(detail.plans.discount?.breakeven, 0) + ' 元' : '无论多少都不赚' }}。
            本金上限（日限额 与 成交额×10% 取小）：{{ detail.max_amount ? yuan(detail.max_amount, 0) + ' 元' : '无明确上限' }}。
            上限之外的部分要承担冲击成本（卖出会砸价）。
          </div>
        </div>

        <!-- 该基金历史同类信号实测 -->
        <div v-if="detail.hist_arb && detail.hist_arb.length" class="arb-sec">
          <div class="arb-sec__head">
            <b>该基金历史同类信号</b>
            <span class="arb-sec__sub">T+3 卖出 · 扣费后 · 按 1 万元本金 · 用本基金自己的历史算</span>
          </div>
          <table class="arb-table">
            <thead>
              <tr>
                <th>入场阈值</th><th class="r">样本</th><th class="r">平均</th>
                <th class="r">中位</th><th class="r">胜率</th><th class="r">溢价收敛</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="h in detail.hist_arb" :key="h.threshold">
                <td>溢价 ≥{{ h.threshold }}%</td>
                <td class="r">{{ h.n }}</td>
                <td class="r" :class="sign(h.mean_pct)">{{ pct(h.mean_pct) }}</td>
                <td class="r" :class="sign(h.median_pct)">{{ pct(h.median_pct) }}</td>
                <td class="r">{{ h.win_pct }}%</td>
                <td class="r">{{ h.premium_t }}% → {{ h.premium_t3 }}%</td>
              </tr>
            </tbody>
          </table>
          <div class="arb-warn" style="margin-top:8px">
            读法：T 日看到的溢价（第一列右上角）在 3 天里平均会收敛掉大半 —— 「净空间」是当天快照，
            历史实现才是这类信号的真实水平。统计含样本重叠、除息日等个别价格-净值不同步日，不含历史申购状态与限额约束（高溢价样本常出现在暂停申购期）。
          </div>
        </div>

        <!-- 历史折溢价 -->
        <div class="arb-sec">
          <div class="arb-sec__head">
            <b>历史折溢价率</b>
            <div class="arb-sec__tools">
              <button class="arb-btn arb-btn--mini" :class="{ 'is-on': histDays === 120 }" @click="histDays = 120">120日</button>
              <button class="arb-btn arb-btn--mini" :class="{ 'is-on': histDays === 250 }" @click="histDays = 250">250日</button>
              <button class="arb-btn arb-btn--mini" :class="{ 'is-on': histDays === 1000 }" @click="histDays = 1000">全量</button>
            </div>
          </div>
          <div ref="detailChartEl" class="arb-chart" />
          <div v-if="detail.stats" class="arb-stats">
            <span>样本 {{ detail.stats.n }} 日</span>
            <span>中位 {{ pctPlain(detail.stats.median_pct, 3) }}</span>
            <span>10%~90% 分位 {{ pctPlain(detail.stats.p10_pct, 2) }} ~ {{ pctPlain(detail.stats.p90_pct, 2) }}</span>
            <span>极值 {{ pctPlain(detail.stats.min_pct, 2) }} ~ {{ pctPlain(detail.stats.max_pct, 2) }}</span>
            <span>溢价&gt;1% 天数 {{ detail.stats.days_above_1pct }}</span>
            <span>溢价&gt;2% 天数 {{ detail.stats.days_above_2pct }}</span>
          </div>
        </div>

        <!-- 费率表 -->
        <div class="arb-sec">
          <div class="arb-sec__head"><b>赎回费率分档</b><span class="arb-sec__sub">决定折价套利能不能做</span></div>
          <table class="arb-table">
            <thead><tr><th>持有期限</th><th class="r">赎回费率</th></tr></thead>
            <tbody>
              <tr v-for="t in detail.redeem_tiers" :key="t.label">
                <td>{{ t.label }}</td>
                <td class="r">{{ pctPlain(t.rate_pct, 2) }}</td>
              </tr>
              <tr v-if="!detail.redeem_tiers.length"><td colspan="2" class="arb-muted">未取到费率（按默认档位估算）</td></tr>
            </tbody>
          </table>
          <div v-if="detail.buy_tiers.length" class="arb-sec__sub" style="margin-top:6px">
            申购费率：<span v-for="b in detail.buy_tiers" :key="b.amount">{{ b.amount }} {{ b.rate }}　</span>
          </div>
        </div>

        <!-- 流程时间轴 -->
        <div class="arb-sec">
          <div class="arb-sec__head"><b>操作流程（占 {{ cfg.premium_days }}/{{ cfg.discount_days }} 天）</b></div>
          <div class="arb-flow">
            <div class="arb-flow__row">
              <span class="arb-flow__tag up">溢价</span>
              T 日 15:00 前场外申购（按当日净值）→ T+1 确认 → T+2 份额可转托管 → 转托管 T+1 → 场内卖出
            </div>
            <div class="arb-flow__row">
              <span class="arb-flow__tag down">折价</span>
              T 日场内买入 → T+1 可转托管到场外 → 提交赎回（按当日净值）→ 资金 T+1~T+7 到账（QDII 更慢）
            </div>
          </div>
          <div class="arb-warn">
            风险：① 溢价在 T+2~T+3 里可能消失（价格波动吃掉空间）；② 基金可能暂停申购/限大额（溢价套利前提失效）；
            ③ QDII 净值滞后，看到的折溢价率可能失真；④ 场内成交额小 → 卖出时冲击成本高；⑤ 持有期内净值自身涨跌。
            这些都是真实交易约束，本页只做算术，不构成建议。
          </div>
        </div>
      </template>
    </Drawer>
  </AppPage>
</template>

<style scoped>
.arb-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.arb-date { font-size: 12px; color: var(--text-dim); margin-right: 4px; }
.arb-lag { font-style: normal; color: var(--up); }
.arb-btn {
  display: inline-flex; align-items: center; gap: 5px; padding: 5px 10px; border-radius: 8px;
  border: 1px solid var(--border-soft); background: var(--bg-raised); color: var(--text);
  font-size: 12.5px; cursor: pointer;
}
.arb-btn:hover:not(:disabled) { background: var(--bg-hover); }
.arb-btn:disabled { opacity: .55; cursor: default; }
.arb-btn--ghost { background: transparent; }
.arb-btn--mini { padding: 2px 8px; font-size: 11.5px; }
.arb-btn--mini.is-on { border-color: var(--accent); color: var(--accent); }

.arb-tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px; margin: 14px 0; }

/* 可执行机会面板 */
.arb-opps { display: flex; flex-direction: column; gap: 6px; }
.arb-opp {
  display: grid; grid-template-columns: 46px minmax(120px, 1fr) 66px 96px 170px;
  align-items: center; gap: 12px; width: 100%; padding: 8px 12px; cursor: pointer; text-align: left;
  border: 1px solid var(--border-soft); border-radius: 10px; background: var(--bg-raised); color: var(--text);
  font-size: 13px;
}
.arb-opp:hover { background: var(--bg-hover); border-color: var(--border-strong); }
.arb-opp__dir {
  display: inline-block; text-align: center; padding: 1px 0; border-radius: 6px; font-size: 11.5px;
  border: 1px solid var(--border-soft);
}
.arb-opp__dir.up { color: var(--up); border-color: color-mix(in srgb, var(--up) 40%, transparent); }
.arb-opp__dir.down { color: var(--down); border-color: color-mix(in srgb, var(--down) 40%, transparent); }
.arb-opp__name { font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.arb-opp__code { color: var(--text-dim); font-size: 12px; }
.arb-opp__space { font-weight: 700; text-align: right; font-variant-numeric: tabular-nums; }
.arb-opp__window { text-align: right; color: var(--text-dim); font-size: 12px; white-space: nowrap; }
@media (max-width: 760px) {
  .arb-opp { grid-template-columns: 46px 1fr 96px; }
  .arb-opp__code, .arb-opp__window { display: none; }
}

/* 总览折叠块 */
.arb-ov {
  margin: 14px 0; border: 1px solid var(--border-soft); border-radius: 12px;
  background: linear-gradient(var(--bg-raised), var(--bg-panel)); overflow: hidden;
}
.arb-ov__head {
  display: flex; align-items: center; gap: 8px; width: 100%; padding: 10px 14px;
  background: transparent; border: 0; cursor: pointer; color: var(--text); font-size: 13px; text-align: left;
}
.arb-ov__head:hover { background: var(--bg-hover); }
.arb-ov__head b { font-size: 13px; }
.arb-ov__sum { color: var(--text-dim); font-size: 12.5px; }
.arb-ov__sum em { font-style: normal; color: var(--text); font-weight: 600; }
.arb-ov__hint { margin-left: auto; font-size: 11.5px; color: var(--text-dim); }
.arb-ov.is-open .arb-tiles { margin: 0 14px 14px; }
.arb-ov__body { padding: 0 14px 14px; }

.cfg-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 10px; }
.cfg-item { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--text-dim); }
.cfg-item input {
  padding: 5px 8px; border-radius: 7px; border: 1px solid var(--border-soft);
  background: var(--bg-raised); color: var(--text); font-size: 13px;
}
.cfg-tip { margin-top: 10px; font-size: 12px; color: var(--text-dim); line-height: 1.7; }

.arb-filters { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; margin-bottom: 10px; }
.arb-check { display: inline-flex; align-items: center; gap: 6px; font-size: 12.5px; color: var(--text-dim); cursor: pointer; }
.arb-min { display: inline-flex; align-items: center; gap: 6px; font-size: 12.5px; color: var(--text-dim); }
.arb-min input {
  width: 64px; padding: 4px 7px; border-radius: 7px; border: 1px solid var(--border-soft);
  background: var(--bg-raised); color: var(--text); font-size: 12.5px;
}
.arb-count { margin-left: auto; font-size: 12px; color: var(--text-dim); }
.arb-panelctl { font-size: 12px; color: var(--text-dim); display: inline-flex; align-items: center; gap: 4px; }
.arb-panelctl input {
  width: 56px; padding: 3px 6px; border-radius: 7px; border: 1px solid var(--border-soft);
  background: var(--bg-raised); color: var(--text); font-size: 12px;
}
.arb-excluded { margin-top: 10px; font-size: 11.5px; color: var(--text-dim); }
.arb-sub { font-size: 11.5px; color: var(--text-dim); opacity: .85; }
.arb-name { font-weight: 500; }
.arb-weak { color: var(--warn, #d08770); }
.arb-suspend { color: var(--down); }
.arb-tag {
  display: inline-block; margin: 1px 4px 1px 0; padding: 1px 6px; border-radius: 6px; font-size: 11px;
  background: var(--bg-raised); border: 1px solid var(--border-soft); color: var(--text-dim);
}
.arb-tag--ok { color: var(--accent); border-color: color-mix(in srgb, var(--accent) 45%, transparent); }
.arb-tag--warn { color: var(--up); border-color: color-mix(in srgb, var(--up) 45%, transparent); }
.arb-note { margin-top: 12px; font-size: 12px; color: var(--text-dim); line-height: 1.75; }

.arb-loading { padding: 24px; color: var(--text-dim); }
.arb-d-head { display: flex; flex-direction: column; gap: 8px; padding-bottom: 12px; border-bottom: 1px solid var(--border-soft); }
.arb-d-big { display: flex; align-items: baseline; gap: 10px; }
.arb-d-label { font-size: 12px; color: var(--text-dim); }
.arb-d-value { font-size: 28px; font-weight: 600; }
.arb-d-meta { display: flex; gap: 16px; flex-wrap: wrap; font-size: 12.5px; color: var(--text-dim); }
.arb-d-meta b { color: var(--text); }
.arb-d-tags { display: flex; gap: 4px; flex-wrap: wrap; }

.arb-calc {
  margin-top: 10px; padding: 12px; border-radius: 10px;
  border: 1px solid var(--border-soft); background: var(--bg-raised);
}
.arb-calc__head { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.arb-calc__ctl { display: flex; align-items: center; gap: 6px; font-size: 12.5px; color: var(--text-dim); }
.arb-calc__ctl input {
  width: 96px; padding: 5px 8px; border-radius: 8px; border: 1px solid var(--border-strong);
  background: var(--bg-panel); color: var(--text); font-size: 14px; font-weight: 600; text-align: right;
}
.arb-calc__rows { margin-top: 10px; display: flex; flex-direction: column; gap: 5px; font-size: 12.5px; }
.arb-calc__rows > div { display: flex; justify-content: space-between; gap: 12px; }
.arb-calc__rows span { color: var(--text-dim); }
.arb-calc__rows i { font-style: normal; text-align: right; }
.arb-calc__rows em { font-style: normal; color: var(--text-dim); }
.arb-calc__result {
  margin-top: 10px; padding-top: 10px; border-top: 1px dashed var(--border-soft);
  display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap;
}
.arb-calc__label { font-size: 12.5px; color: var(--text-dim); }
.arb-calc__value { font-size: 24px; font-weight: 700; }
.arb-calc__sub { font-size: 12px; color: var(--text-dim); }
.arb-curve { height: 200px; margin-top: 8px; }
.arb-calc__hint {
  margin-top: 8px; padding: 6px 9px; border-radius: 8px; font-size: 12px; line-height: 1.6;
  color: var(--up); border: 1px solid color-mix(in srgb, var(--up) 35%, transparent);
}
.arb-calc__other { margin-top: 8px; font-size: 12px; color: var(--text-dim); }
.arb-calc__note { margin-left: 4px; }

.arb-plans { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 12px; }
@media (max-width: 620px) { .arb-plans { grid-template-columns: 1fr; } }
.arb-plan { border: 1px solid var(--border-soft); border-radius: 10px; padding: 10px 12px; background: var(--bg-raised); }
.arb-plan__head { display: flex; flex-direction: column; gap: 2px; margin-bottom: 8px; }
.arb-plan__sub { font-size: 11.5px; color: var(--text-dim); }
.arb-plan__rows { display: flex; flex-direction: column; gap: 5px; font-size: 12.5px; }
.arb-plan__rows > div { display: flex; justify-content: space-between; gap: 10px; }
.arb-plan__rows span { color: var(--text-dim); }
.arb-plan__rows i { font-style: normal; color: var(--text); text-align: right; }
.arb-plan__net { border-top: 1px dashed var(--border-soft); padding-top: 6px; margin-top: 2px; font-weight: 600; }

.arb-sec { margin-top: 16px; }
.arb-sec__head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
.arb-sec__sub { font-size: 11.5px; color: var(--text-dim); font-weight: 400; }
.arb-sec__tools { display: flex; gap: 4px; }
.arb-chart { height: 190px; }
.arb-stats { display: flex; gap: 12px; flex-wrap: wrap; font-size: 11.5px; color: var(--text-dim); margin-top: 6px; }
.arb-table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.arb-table th, .arb-table td { padding: 5px 8px; border-bottom: 1px solid var(--border-soft); text-align: left; }
.arb-table th.r, .arb-table td.r { text-align: right; }
.arb-muted { color: var(--text-dim); }

.arb-flow { display: flex; flex-direction: column; gap: 6px; }
.arb-flow__row { font-size: 12.5px; color: var(--text-dim); line-height: 1.7; }
.arb-flow__tag { display: inline-block; margin-right: 6px; padding: 1px 6px; border-radius: 6px; font-size: 11px; border: 1px solid var(--border-soft); }
.arb-flow__tag.up { color: var(--up); border-color: color-mix(in srgb, var(--up) 40%, transparent); }
.arb-flow__tag.down { color: var(--down); border-color: color-mix(in srgb, var(--down) 40%, transparent); }
.arb-warn {
  margin-top: 10px; padding: 8px 10px; border-radius: 8px; font-size: 12px; line-height: 1.75;
  color: var(--text-dim); background: var(--bg-raised); border: 1px solid var(--border-soft);
}
</style>
