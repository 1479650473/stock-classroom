<script setup lang="ts">
import { onMounted, ref } from 'vue'
import PageHeader from '@/components/PageHeader.vue'
import Card from '@/components/Card.vue'
import StatCard from '@/components/StatCard.vue'
import Skeleton from '@/components/Skeleton.vue'
import EmptyState from '@/components/EmptyState.vue'
import Icon from '@/components/Icon.vue'
import { listAccounts, getPositions } from '@/api'
import type { AccountSummary, Position } from '@/api'

const accounts = ref<AccountSummary[]>([])
const selectedId = ref<number | null>(null)
const positions = ref<Position[]>([])
const loading = ref(true)

onMounted(async () => {
  try {
    accounts.value = await listAccounts()
    if (accounts.value.length) {
      selectedId.value = accounts.value[0].account_id
      await loadPositions()
    }
  } finally { loading.value = false }
})

async function loadPositions() {
  if (!selectedId.value) return
  loading.value = true
  try { positions.value = await getPositions(selectedId.value) } finally { loading.value = false }
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
    <PageHeader title="持仓" subtitle="纸面盘账本">
      <template #right>
        <select v-if="accounts.length > 1" v-model="selectedId" class="sel" @change="loadPositions">
          <option v-for="a in accounts" :key="a.account_id" :value="a.account_id">{{ a.name }}</option>
        </select>
      </template>
    </PageHeader>

    <Skeleton v-if="loading && !positions.length" />

    <EmptyState v-if="!loading && !accounts.length" message="暂无账户，请先在交易页面创建" />

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
</style>
