<script setup lang="ts">
import { onMounted, ref } from 'vue'
import PageHeader from '@/components/PageHeader.vue'
import Card from '@/components/Card.vue'
import StatCard from '@/components/StatCard.vue'
import Skeleton from '@/components/Skeleton.vue'
import EmptyState from '@/components/EmptyState.vue'
import Icon from '@/components/Icon.vue'
import { getRegime, getFactors, getStrategies } from '@/api'
import type { RegimeData, FactorDef, StrategyDef } from '@/api'

const regime = ref<RegimeData | null>(null)
const factors = ref<FactorDef[]>([])
const strategies = ref<StrategyDef[]>([])
const loading = ref(true)
const regimeLoading = ref(true)

onMounted(async () => {
  try {
    const [f, s] = await Promise.all([getFactors(), getStrategies()])
    factors.value = f
    strategies.value = s
  } finally { loading.value = false }
  try { regime.value = await getRegime() } finally { regimeLoading.value = false }
})

const regimeColor = (r: string) => r === 'bull' ? 'up' : r === 'bear' ? 'down' : 'flat'
const regimeLabel: Record<string, string> = { bull: '牛市', bear: '熊市', range: '震荡' }
</script>

<template>
  <div class="research">
    <PageHeader title="研究" subtitle="市场环境 · 因子分析 · 策略进化" />

    <!-- regime -->
    <section class="sec">
      <h2 class="sec-title">
        <Icon name="market" :size="18" />
        市场环境判断
      </h2>
      <Skeleton v-if="regimeLoading && !regime" />
      <Card v-else-if="regime" highlight>
        <div class="regime-grid">
          <div class="regime-main">
            <div class="regime-label muted">当前环境</div>
            <div :class="['regime-val', 'num', regimeColor(regime.regime)]">
              {{ regime.regime_cn }}
            </div>
            <div class="regime-sub muted">推荐策略：{{ regime.suggest_strategy }}</div>
          </div>
          <div class="regime-meta">
            <div class="meta-row" v-if="regime.score">
              <span class="meta-k">MA20</span>
              <span class="meta-v num">{{ (regime.score as Record<string,unknown>).ma20 as number }}</span>
            </div>
            <div class="meta-row" v-if="regime.score">
              <span class="meta-k">MA60</span>
              <span class="meta-v num">{{ (regime.score as Record<string,unknown>).ma60 as number }}</span>
            </div>
            <div class="meta-row" v-if="regime.sys_risk">
              <span class="meta-k">系统风险</span>
              <span :class="['meta-v', 'num', (regime.sys_risk as Record<string,unknown>).triggered ? 'up' : 'down']">
                {{ (regime.sys_risk as Record<string,unknown>).triggered ? '已触发' : '正常' }}
              </span>
            </div>
            <div class="meta-row" v-if="regime.rotation">
              <span class="meta-k">主策略</span>
              <span class="meta-v gold">{{ (regime.rotation as Record<string,unknown>).primary as string }}</span>
            </div>
          </div>
        </div>
      </Card>
      <EmptyState v-else-if="!regimeLoading" message="无法获取市场环境数据" />
    </section>

    <!-- factors -->
    <section class="sec">
      <h2 class="sec-title">
        <Icon name="research" :size="18" />
        因子库
      </h2>
      <div class="factor-grid" v-if="factors.length">
        <Card v-for="f in factors" :key="f.id" padding>
          <div class="factor-hd">
            <span class="factor-id">{{ f.id }}</span>
            <span class="factor-group">{{ f.group }}</span>
          </div>
          <div class="factor-name">{{ f.name }}</div>
          <div class="factor-desc muted">{{ f.desc }}</div>
        </Card>
      </div>
      <Skeleton v-else-if="loading" />
    </section>

    <!-- strategies -->
    <section class="sec">
      <h2 class="sec-title">
        <Icon name="layers" :size="18" />
        策略库
      </h2>
      <div class="strat-list" v-if="strategies.length">
        <Card v-for="s in strategies" :key="s.id" padding highlight>
          <div class="strat-hd">
            <span class="strat-name gold">{{ s.name }}</span>
            <span class="strat-kind">{{ s.kind === 'multi_factor' ? '多因子' : s.kind }}</span>
          </div>
          <div class="strat-desc">{{ s.desc }}</div>
          <div class="strat-meta muted">
            因子: {{ s.factors.join(' + ') }} · 持仓{{ s.rebalance_bars }}日 · Top {{ (s.top_k_pct * 100).toFixed(0) }}%
          </div>
        </Card>
      </div>
      <Skeleton v-else-if="loading" />
    </section>
  </div>
</template>

<style scoped>
.research { max-width: 1000px; }
.sec { margin-bottom: var(--sp-6); }
.sec-title {
  font-size: var(--fs-lg); font-weight: 600; color: var(--text); margin: 0 0 var(--sp-4);
  display: flex; align-items: center; gap: var(--sp-2);
}
.regime-grid { display: flex; gap: var(--sp-8); align-items: center; }
.regime-main { flex: 1; }
.regime-label { font-size: var(--fs-sm); margin-bottom: 2px; }
.regime-val { font-size: var(--fs-hero); font-weight: 800; margin: var(--sp-1) 0; }
.regime-sub { font-size: var(--fs-md); color: var(--text-sub); }
.regime-meta { display: flex; flex-direction: column; gap: var(--sp-2); }
.meta-row { display: flex; justify-content: space-between; gap: var(--sp-4); }
.meta-k { color: var(--text-sub); font-size: var(--fs-sm); min-width: 60px; }
.meta-v { font-size: var(--fs-md); font-weight: 500; }
.factor-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: var(--sp-3); }
.factor-hd { display: flex; justify-content: space-between; align-items: center; margin-bottom: var(--sp-1); }
.factor-id { font-family: var(--font-mono); font-size: var(--fs-sm); color: var(--accent); font-weight: 600; }
.factor-group { font-size: var(--fs-xs); color: var(--text-faint); border: 1px solid var(--border); padding: 1px 6px; border-radius: var(--radius-pill); }
.factor-name { font-size: var(--fs-md); font-weight: 600; color: var(--text); margin-bottom: 2px; }
.factor-desc { font-size: var(--fs-sm); line-height: 1.4; }
.strat-list { display: flex; flex-direction: column; gap: var(--sp-3); }
.strat-hd { display: flex; align-items: center; gap: var(--sp-3); margin-bottom: var(--sp-1); }
.strat-name { font-size: var(--fs-lg); font-weight: 700; }
.strat-kind { font-size: var(--fs-xs); color: var(--text-faint); border: 1px solid var(--border); padding: 1px 6px; border-radius: var(--radius-pill); }
.strat-desc { font-size: var(--fs-md); color: var(--text-sub); margin-bottom: var(--sp-1); }
.strat-meta { font-size: var(--fs-sm); }
.gold { color: var(--gold); }
.muted { color: var(--text-faint); }
.up { color: var(--up); } .down { color: var(--down); } .flat { color: var(--text-faint); }
</style>
