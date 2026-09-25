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
import Icon from '@/components/Icon.vue'
import { usePersistedRef } from '@/composables/usePersistedRef'
import { useEChart } from '@/composables/useEChart'
import { useJobsStore } from '@/stores/jobs'
import {
  getArbList, getArbDetail, getArbStats, syncArb,
  type ArbItem, type ArbDetail, type ArbPlan,
} from '@/api'

const jobs = useJobsStore()

// ---------------- 过滤 & 成本参数（持久化） ----------------
const direction = usePersistedRef<string>('arb.direction', 'all')
const minSpace = usePersistedRef<number>('arb.minSpace', 0)
const onlyOpen = usePersistedRef<boolean>('arb.onlyOpen', false)
const showCfg = ref(false)
/** 总览面板：平时折叠，只作一个功能块 */
const showOverview = usePersistedRef<boolean>('arb.showOverview', false)

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

onMounted(() => { load(); loadStats() })
watch([direction, minSpace, onlyOpen], load)

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
const dataDate = computed(() => (stats.value?.daily_last as string) || (rows.value[0]?.price_date ?? '—'))
const navDate = computed(() => (stats.value?.nav_last as string) || '')

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
  () => { if (!syncing.value) { load(); loadStats() } },
)

// ---------------- 明细抽屉 ----------------
const detailOpen = ref(false)
const detail = ref<ArbDetail | null>(null)
const detailLoading = ref(false)
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
  try {
    detail.value = await getArbDetail(item.code, { ...cfgParams.value, hist_days: histDays.value })
    detailLoading.value = false   // 先切到详情分支，图表容器才会挂载
    await nextTick()
    drawDetail()
  } catch {
    detailLoading.value = false
  }
}
watch(histDays, async () => {
  if (detail.value) {
    detail.value = await getArbDetail(detail.value.code, { ...cfgParams.value, hist_days: histDays.value })
    await nextTick(); drawDetail()
  }
})
watch([() => cfg.value.amount, () => cfg.value.commission_rate, () => cfg.value.buy_fee_discount], async () => {
  if (detail.value && detailOpen.value) {
    detail.value = await getArbDetail(detail.value.code, { ...cfgParams.value, hist_days: histDays.value })
    await nextTick(); drawDetail()
  }
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
  { key: 'amount', title: '成交额', width: '84px', align: 'right' as const, sortable: true },
  { key: 'purchase_status', title: '申购', width: '76px' },
  { key: 'min_amount', title: '起点', width: '72px', align: 'right' as const },
  { key: 'tags', title: '标签', width: '150px' },
]
</script>

<template>
  <AppPage title="基金套利" subtitle="LOF 折溢价：场内价 vs 单位净值，扣申购/赎回/佣金/转托管/滑点后的净空间">
    <template #actions>
      <div class="arb-actions">
        <span class="arb-date">
          数据：行情 {{ dataDate }}<template v-if="navDate"> · 净值 {{ navDate }}</template>
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

    <!-- 总览：可折叠功能块（默认收起） -->
    <section class="arb-ov" :class="{ 'is-open': showOverview }">
      <button class="arb-ov__head" @click="showOverview = !showOverview">
        <Icon :name="showOverview ? 'chevron-down' : 'chevron-right'" :size="16" />
        <b>总览</b>
        <span class="arb-ov__sum">
          溢价机会 <em class="up">{{ counts.premProfitable }}</em> 只 · 折价机会 <em class="down">{{ counts.discProfitable }}</em> 只 ·
          最大净空间 <em>{{ Number.isFinite(counts.maxSpace) && counts.maxSpace > -9 ? counts.maxSpace.toFixed(2) + '%' : '—' }}</em> ·
          覆盖 LOF {{ Number(stats?.lof_count ?? 0) }} 只
        </span>
        <span class="arb-ov__hint">{{ showOverview ? '收起' : '展开' }}</span>
      </button>
      <div v-if="showOverview" class="arb-tiles">
        <StatTile label="溢价机会（扣费后为正）" :value="counts.premProfitable" unit="只" :hint="`共 ${counts.prem} 只溢价`" trend="up" />
        <StatTile label="折价机会（扣费后为正）" :value="counts.discProfitable" unit="只" :hint="`共 ${counts.disc} 只折价`" trend="down" />
        <StatTile label="最大净空间" :value="Number.isFinite(counts.maxSpace) && counts.maxSpace > -9 ? counts.maxSpace.toFixed(3) : '—'" unit="%" hint="已扣全部费用" />
        <StatTile label="覆盖 LOF" :value="Number(stats?.lof_count ?? 0)" unit="只" :hint="`净值 ${Number(stats?.nav_rows ?? 0).toLocaleString()} 条`" />
      </div>
    </section>

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

    <SectionCard padded>
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
        <span class="arb-count">共 {{ total }} 只可盈利<template v-if="total !== rows.length">（显示前 {{ rows.length }}）</template></span>
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
    </SectionCard>

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

        <!-- 成本拆解 -->
        <div class="arb-plans">
          <div v-if="detail.plans.premium" class="arb-plan">
            <div class="arb-plan__head">
              <b>溢价套利</b><span class="arb-plan__sub">申购净值 → 场内卖出 · 约 {{ detail.plans.premium.days }} 天</span>
            </div>
            <div class="arb-plan__rows">
              <div><span>申购费</span><i>{{ yuan(detail.plans.premium.buy_fee, 2) }} 元<template v-if="detail.fee_rate_pct !== null && detail.fee_rate_pct !== undefined">（{{ pctPlain(detail.fee_rate_pct * (detail.cfg?.buy_fee_discount ?? 1), 2) }}）</template></i></div>
              <div><span>卖出佣金</span><i>{{ yuan(detail.plans.premium.commission, 2) }} 元</i></div>
              <div><span>滑点成本</span><i>{{ yuan(detail.plans.premium.slippage_cost, 2) }} 元</i></div>
              <div><span>转托管费</span><i>{{ yuan(detail.plans.premium.transfer_fee, 2) }} 元</i></div>
              <div><span>费用合计</span><i>{{ pctPlain(detail.plans.premium.fee_pct, 3) }}</i></div>
              <div class="arb-plan__net">
                <span>净空间</span>
                <i :class="sign(detail.plans.premium.space_pct)">{{ pct(detail.plans.premium.space_pct) }} · 每万元 {{ yuan(detail.plans.premium.profit, 1) }} 元</i>
              </div>
              <div><span>折算年化</span><i :class="sign(detail.plans.premium.annual_pct)">{{ pct(detail.plans.premium.annual_pct) }}</i></div>
            </div>
          </div>

          <div v-if="detail.plans.discount" class="arb-plan">
            <div class="arb-plan__head">
              <b>折价套利</b><span class="arb-plan__sub">场内买入 → 赎回 · 最短 {{ detail.plans.discount.days }} 天</span>
            </div>
            <div class="arb-plan__rows">
              <div><span>买入佣金</span><i>{{ yuan(detail.plans.discount.commission, 2) }} 元</i></div>
              <div>
                <span>赎回费</span>
                <i>{{ yuan(detail.plans.discount.redeem_fee, 2) }} 元（{{ pctPlain(detail.plans.discount.redeem_rate_pct, 2) }}<template v-if="detail.plans.discount.tier_label">，{{ detail.plans.discount.tier_label }}</template>）</i>
              </div>
              <div v-if="detail.plans.discount_best">
                <span>持满 {{ detail.plans.discount_best.days }} 天后赎回</span>
                <i :class="sign(detail.plans.discount_best.space_pct)">{{ pct(detail.plans.discount_best.space_pct) }}（费率 {{ pctPlain(detail.plans.discount_best.redeem_rate_pct, 2) }}）</i>
              </div>
              <div class="arb-plan__net">
                <span>净空间</span>
                <i :class="sign(detail.plans.discount.space_pct)">{{ pct(detail.plans.discount.space_pct) }} · 每万元 {{ yuan(detail.plans.discount.profit, 1) }} 元</i>
              </div>
              <div><span>折算年化</span><i :class="sign(detail.plans.discount.annual_pct)">{{ pct(detail.plans.discount.annual_pct) }}</i></div>
            </div>
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

.arb-tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px; margin: 0 0 12px; }

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
.arb-sub { font-size: 11.5px; color: var(--text-dim); opacity: .85; }
.arb-name { font-weight: 500; }
.arb-weak { color: var(--warn, #d08770); }
.arb-suspend { color: var(--down); }
.arb-tag {
  display: inline-block; margin: 1px 4px 1px 0; padding: 1px 6px; border-radius: 6px; font-size: 11px;
  background: var(--bg-raised); border: 1px solid var(--border-soft); color: var(--text-dim);
}
.arb-note { margin-top: 12px; font-size: 12px; color: var(--text-dim); line-height: 1.75; }

.arb-loading { padding: 24px; color: var(--text-dim); }
.arb-d-head { display: flex; flex-direction: column; gap: 8px; padding-bottom: 12px; border-bottom: 1px solid var(--border-soft); }
.arb-d-big { display: flex; align-items: baseline; gap: 10px; }
.arb-d-label { font-size: 12px; color: var(--text-dim); }
.arb-d-value { font-size: 28px; font-weight: 600; }
.arb-d-meta { display: flex; gap: 16px; flex-wrap: wrap; font-size: 12.5px; color: var(--text-dim); }
.arb-d-meta b { color: var(--text); }
.arb-d-tags { display: flex; gap: 4px; flex-wrap: wrap; }

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
