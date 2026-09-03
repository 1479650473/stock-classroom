<script setup lang="ts">
import { onMounted, ref } from 'vue'
import PageHeader from '@/components/PageHeader.vue'
import Card from '@/components/Card.vue'
import StatCard from '@/components/StatCard.vue'
import Skeleton from '@/components/Skeleton.vue'
import EmptyState from '@/components/EmptyState.vue'
import { listAccounts, getPositions, getNavHistory } from '@/api'
import type { AccountSummary, Position } from '@/api'
import { useEChart, cssVar } from '@/composables/useEChart'

const accounts = ref<AccountSummary[]>([])
const selectedId = ref<number | null>(null)
const positions = ref<Position[]>([])
const loading = ref(true)
const loadError = ref('')
const nav = ref<number[]>([])
const navChartEl = ref<HTMLElement | null>(null)

const { draw: drawNav } = useEChart(navChartEl, () => {
  const n = nav.value
  const start = n[0] || 0
  const idx = n.map((v) => start ? +(v / start * 100).toFixed(2) : 0)
  return {
    grid: { left: 50, right: 16, top: 16, bottom: 26 },
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: idx.map((_, i) => i), axisLabel: { show: false } },
    yAxis: { type: 'value', scale: true },
    series: [{
      type: 'line', data: idx, smooth: true, showSymbol: false,
      lineStyle: { color: cssVar('--gold'), width: 2 },
      areaStyle: { color: cssVar('--gold-dim') },
    }],
  }
})

async function loadAccounts() {
  loading.value = true
  loadError.value = ''
  try {
    accounts.value = await listAccounts()
    if (accounts.value.length) {
      if (!selectedId.value || !accounts.value.some(a => a.account_id === selectedId.value)) {
        selectedId.value = accounts.value[0].account_id
      }
      await Promise.all([loadPositions(), loadNav()])
    }
  } catch (e) {
    loadError.value = e instanceof Error ? e.message : '账户加载失败'
  } finally { loading.value = false }
}
onMounted(loadAccounts)

async function loadPositions() {
  if (!selectedId.value) return
  try { positions.value = await getPositions(selectedId.value) }
  catch (e) { loadError.value = e instanceof Error ? e.message : '持仓加载失败' }
}

async function loadNav() {
  if (!selectedId.value) return
  try {
    const r = await getNavHistory(selectedId.value)
    nav.value = r.nav || []
    navChartEl.value && drawNav()
  } catch { nav.value = [] }
}

async function switchAccount(id: number) {
  selectedId.value = id
  await Promise.all([loadPositions(), loadNav()])
}

function fmtMoney(v: number) {
  if (Math.abs(v) >= 1e8) return (v / 1e8).toFixed(2) + '亿'
  if (Math.abs(v) >= 1e4) return (v / 1e4).toFixed(2) + '万'
  return v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}
function fmtPct(v: number) { return (v >= 0 ? '+' : '') + v.toFixed(2) + '%' }
</script>

<template>
  <div>
    <PageHeader title="持仓" subtitle="纸面盘账本 · 账户净值">
      <template #right>
        <select v-if="accounts.length > 1" v-model="selectedId" class="sel" @change="switchAccount(Number(selectedId))">
          <option v-for="a in accounts" :key="a.account_id" :value="a.account_id">{{ a.name }}</option>
        </select>
      </template>
    </PageHeader>

    <Skeleton v-if="loading && !positions.length" />

    <EmptyState v-if="loadError && !accounts.length" :message="loadError">
      <template #action>
        <button class="retry" @click="loadAccounts">重试</button>
      </template>
    </EmptyState>

    <EmptyState v-if="!loading && !loadError && !accounts.length" message="暂无账户，请先创建账户" />

    <template v-if="accounts.length && selectedId">
      <div class="stats">
        <StatCard label="持仓数" :value="positions.length" unit="只" icon="holdings" />
        <StatCard label="持仓市值" :value="fmtMoney(positions.reduce((s, p) => s + p.market_value, 0))" icon="wallet" />
        <StatCard
          label="浮动盈亏"
          :value="fmtMoney(positions.reduce((s, p) => s + p.float_pnl, 0))"
          :trend="positions.reduce((s, p) => s + p.float_pnl, 0) >= 0 ? 'up' : 'down'"
          :icon="positions.reduce((s, p) => s + p.float_pnl, 0) >= 0 ? 'arrow-up-right' : 'arrow-down-right'"
        />
        <StatCard label="冻结股数" :value="String(positions.reduce((s, p) => s + p.frozen_qty, 0))" icon="alert" />
      </div>

      <!-- 净值曲线 -->
      <Card class="mt">
        <template #header><span class="card-title">账户净值曲线</span></template>
        <div v-if="nav.length > 1" ref="navChartEl" class="nav-chart"></div>
        <EmptyState v-else message="暂无净值数据" />
      </Card>

      <Card class="mt">
        <table class="tbl" v-if="positions.length">
          <thead>
            <tr>
              <th>代码</th>
              <th>名称</th>
              <th class="ar">持仓</th>
              <th class="ar">成本</th>
              <th class="ar">现价</th>
              <th class="ar">市值</th>
              <th class="ar">盈亏</th>
              <th class="ar">盈亏%</th>
              <th>买入日期</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="p in positions" :key="p.id">
              <td class="code">{{ p.code }}</td>
              <td>{{ p.name }}</td>
              <td class="ar num">{{ p.qty.toLocaleString() }}</td>
              <td class="ar num">{{ p.cost_price.toFixed(2) }}</td>
              <td class="ar num">{{ p.current_price.toFixed(2) }}</td>
              <td class="ar num">{{ fmtMoney(p.market_value) }}</td>
              <td class="ar num" :class="p.float_pnl >= 0 ? 'up' : 'down'">
                {{ fmtMoney(p.float_pnl) }}
              </td>
              <td class="ar num" :class="p.float_pnl >= 0 ? 'up' : 'down'">
                {{ fmtPct(p.cost_price ? ((p.current_price - p.cost_price) / p.cost_price) * 100 : 0) }}
              </td>
              <td class="muted">{{ p.last_buy_date }}</td>
            </tr>
          </tbody>
        </table>
        <EmptyState v-else message="空仓" />
      </Card>
    </template>
  </div>
</template>

<style scoped>
.stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: var(--sp-3); margin-bottom: var(--sp-4); }
.mt { margin-top: var(--sp-4); }
.card-title { font-weight: 600; }
.nav-chart { height: 280px; }
.sel {
  background: var(--bg); border: 1px solid var(--border); border-radius: var(--radius-sm);
  padding: 6px 10px; color: var(--text); font-size: var(--fs-sm);
}
.sel:focus { border-color: var(--gold); outline: none; }
.tbl { width: 100%; border-collapse: collapse; font-size: var(--fs-sm); }
.tbl th { padding: 10px var(--sp-3); text-align: left; color: var(--text-sub); border-bottom: 1px solid var(--border); }
.tbl .ar { text-align: right; }
.tbl tr:hover { background: var(--bg-hover); }
.tbl td { padding: 10px var(--sp-3); border-bottom: 1px solid var(--border-soft); color: var(--text); }
.code { font-family: var(--font-mono); }
.up { color: var(--up); } .down { color: var(--down); }
.muted { color: var(--text-faint); font-size: var(--fs-xs); }
.retry {
  padding: 8px 16px; border: 1px solid var(--border); border-radius: var(--radius-sm);
  background: var(--bg-raised); color: var(--text-sub); font-size: var(--fs-sm); cursor: pointer;
}
.retry:hover { border-color: var(--gold); color: var(--gold); }
</style>
