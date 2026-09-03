<script setup lang="ts">
import { onMounted, ref } from 'vue'
import PageHeader from '@/components/PageHeader.vue'
import Card from '@/components/Card.vue'
import StatCard from '@/components/StatCard.vue'
import Skeleton from '@/components/Skeleton.vue'
import EmptyState from '@/components/EmptyState.vue'
import Icon from '@/components/Icon.vue'
import { getOverview } from '@/api'
import type { OverviewData } from '@/api'

const data = ref<OverviewData | null>(null)
const loading = ref(true)
const error = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    data.value = await getOverview()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
}
onMounted(load)

function fmtMoney(v: number) {
  if (v >= 1e8) return (v / 1e8).toFixed(2) + '亿'
  if (v >= 1e4) return (v / 1e4).toFixed(2) + '万'
  return v.toLocaleString()
}
function fmtPct(v: number) {
  return (v >= 0 ? '+' : '') + v.toFixed(2) + '%'
}

const reload = () => load()
</script>

<template>
  <div class="overview">
    <PageHeader title="总览" subtitle="您的量化教室仪表盘" />

    <Skeleton v-if="loading && !data" />

    <EmptyState v-if="error && !data" :message="error">
      <template #action>
        <button class="retry" @click="reload">重试</button>
      </template>
    </EmptyState>

    <template v-if="data">
      <!-- accounts -->
      <section class="sec" v-if="data.accounts?.length">
        <h2 class="sec-title">模拟账户</h2>
        <div class="grid cards-2">
          <Card v-for="acc in data.accounts" :key="acc.account_id" highlight>
            <template #header>
              <span style="font-weight:700">{{ acc.name }}</span>
              <span class="muted">{{ acc.account_id }}</span>
            </template>
            <div class="acc-grid">
              <StatCard label="总资产" :value="fmtMoney(acc.total_assets)" icon="wallet" />
              <StatCard
                label="盈亏"
                :value="fmtMoney(acc.total_profit)"
                :trend="acc.total_profit >= 0 ? 'up' : 'down'"
                :trend-value="fmtPct(acc.total_profit_pct)"
                :icon="acc.total_profit >= 0 ? 'arrow-up-right' : 'arrow-down-right'"
              />
              <StatCard label="持仓" :value="acc.positions" unit="只" />
              <StatCard label="可用余额" :value="fmtMoney(acc.balance)" />
            </div>
          </Card>
        </div>
      </section>

      <!-- strategy -->
      <section class="sec" v-if="data.strategy">
        <h2 class="sec-title">最优策略</h2>
        <div class="grid cards-3">
          <Card highlight>
            <template #header><span class="gold">{{ data.strategy.name }}</span></template>
            <div class="acc-grid">
              <StatCard label="总收益" :value="fmtPct((data.strategy.total_return ?? 0) * 100)" icon="activity" />
              <StatCard label="年化" :value="fmtPct((data.strategy.cagr ?? 0) * 100)" icon="trending" />
              <StatCard label="夏普" :value="(data.strategy.sharpe ?? 0).toFixed(2)" icon="layers" />
              <StatCard label="最大回撤" :value="fmtPct((data.strategy.max_drawdown ?? 0) * 100)" icon="alert" />
            </div>
          </Card>
        </div>
      </section>

      <!-- market indices -->
      <section class="sec" v-if="data.market?.length">
        <h2 class="sec-title">大盘速览</h2>
        <div class="grid cards-4">
          <Card v-for="idx in data.market" :key="idx.code" padding>
            <div class="idx-name">{{ idx.name }}</div>
            <div class="idx-price num">{{ idx.price.toLocaleString() }}</div>
            <div class="idx-chg num" :class="idx.change_pct >= 0 ? 'up' : 'down'">
              {{ fmtPct(idx.change_pct) }}
            </div>
          </Card>
        </div>
      </section>

      <div class="as-of muted">数据时间：{{ data.as_of }}</div>
    </template>
  </div>
</template>

<style scoped>
.overview { max-width: 1100px; }
.sec { margin-bottom: var(--sp-6); }
.sec-title {
  font-size: var(--fs-lg);
  font-weight: 600;
  color: var(--text);
  margin: 0 0 var(--sp-4);
}
.grid { display: grid; gap: var(--sp-4); }
.cards-2 { grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); }
.cards-3 { grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); }
.cards-4 { grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); }
.acc-grid { display: grid; grid-template-columns: 1fr 1fr; gap: var(--sp-3); }
.gold { color: var(--gold); font-weight: 700; }
.muted { color: var(--text-faint); font-size: var(--fs-sm); margin-left: auto; }
.idx-name { font-size: var(--fs-sm); color: var(--text-sub); margin-bottom: var(--sp-1); }
.idx-price { font-size: var(--fs-xl); font-weight: 700; }
.idx-chg { font-size: var(--fs-md); font-weight: 500; }
.as-of { margin-top: var(--sp-6); font-size: var(--fs-xs); }
.up { color: var(--up); }
.down { color: var(--down); }
.retry {
  padding: 8px 16px; border: 1px solid var(--border); border-radius: var(--radius-sm);
  background: var(--bg-raised); color: var(--text-sub); font-size: var(--fs-sm); cursor: pointer;
}
.retry:hover { border-color: var(--gold); color: var(--gold); }
</style>
