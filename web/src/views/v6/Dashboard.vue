<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import AppPage from '@/components/ui/AppPage.vue'
import SectionCard from '@/components/ui/SectionCard.vue'
import StatTile from '@/components/ui/StatTile.vue'
import EmptyGuide from '@/components/ui/EmptyGuide.vue'
import LoadingBlock from '@/components/ui/LoadingBlock.vue'
import Icon from '@/components/Icon.vue'
import { getOverview, getPicks } from '@/api'
import type { OverviewData, PickItem } from '@/api'

const router = useRouter()
const data = ref<OverviewData | null>(null)
const picks = ref<PickItem[]>([])
const loading = ref(true)
const error = ref('')

const totalAssets = computed(() => data.value?.accounts?.reduce((s, a) => s + a.total_assets, 0) ?? 0)
const totalProfit = computed(() => data.value?.accounts?.reduce((s, a) => s + a.total_profit, 0) ?? 0)
const totalPositions = computed(() => data.value?.accounts?.reduce((s, a) => s + a.positions, 0) ?? 0)
const totalBalance = computed(() => data.value?.accounts?.reduce((s, a) => s + a.balance, 0) ?? 0)

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [ov, pk] = await Promise.allSettled([getOverview(), getPicks(5)])
    if (ov.status === 'fulfilled') data.value = ov.value
    else throw ov.reason
    if (pk.status === 'fulfilled') picks.value = pk.value.items
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
}
onMounted(load)

function go(path: string) { router.push(path) }

function fmtMoney(v: number) {
  if (Math.abs(v) >= 1e8) return (v / 1e8).toFixed(2) + '亿'
  if (Math.abs(v) >= 1e4) return (v / 1e4).toFixed(2) + '万'
  return v.toLocaleString(undefined, { maximumFractionDigits: 2 })
}
function fmtPct(v: number) { return (v >= 0 ? '+' : '') + v.toFixed(2) + '%' }

const QUICK = [
  { icon: 'refresh', label: '更新数据', desc: '拉取最新 K 线与基本面', to: '/data' },
  { icon: 'picks', label: '运行选股', desc: '多因子评分生成候选', to: '/trade?tab=picks' },
  { icon: 'backtest', label: '策略回测', desc: '验证策略历史表现', to: '/strategy?tab=backtest' },
  { icon: 'play', label: '策略回放', desc: '逐日复盘买卖点', to: '/strategy?tab=replay' },
]
</script>

<template>
  <AppPage title="工作台" subtitle="账户、关注与快捷操作，一眼掌握">
    <template #actions>
      <button class="ui-btn" @click="load"><Icon name="refresh" :size="14" /><span>刷新</span></button>
      <button class="ui-btn ui-btn--primary" @click="go('/trade?tab=picks')">
        <Icon name="picks" :size="14" /><span>去选股</span>
      </button>
    </template>

    <LoadingBlock v-if="loading && !data" :rows="6" />

    <EmptyGuide v-else-if="error && !data" icon="alert" title="加载失败" :desc="error">
      <template #action><button class="ui-btn" @click="load">重试</button></template>
    </EmptyGuide>

    <template v-else-if="data">
      <!-- 账户概览 -->
      <div class="metrics">
        <StatTile label="总资产" :value="fmtMoney(totalAssets)" icon="wallet" />
        <StatTile
          label="总盈亏"
          :value="fmtMoney(totalProfit)"
          :trend="totalProfit >= 0 ? 'up' : 'down'"
          :hint="totalAssets ? fmtPct((totalProfit / (totalAssets - totalProfit)) * 100) : '—'"
          :hint-trend="totalProfit >= 0 ? 'up' : 'down'"
        />
        <StatTile label="持仓" :value="totalPositions" unit="只" />
        <StatTile label="可用余额" :value="fmtMoney(totalBalance)" />
        <StatTile
          v-if="data.strategy"
          label="最优策略"
          :value="data.strategy.name"
          :hint="`总收益 ${fmtPct((data.strategy.total_return ?? 0) * 100)} · 夏普 ${(data.strategy.sharpe ?? 0).toFixed(2)}`"
        />
      </div>

      <div class="cols">
        <!-- 今日关注 -->
        <SectionCard title="今日关注" desc="多因子评分 Top 5">
          <template #actions>
            <button class="ui-btn ui-btn--sm ui-btn--ghost" @click="go('/trade?tab=picks')">
              全部<Icon name="chevron-right" :size="13" />
            </button>
          </template>
          <div v-if="picks.length" class="watchlist">
            <button
              v-for="(p, i) in picks"
              :key="p.code"
              class="watch-item"
              @click="go(`/market?tab=stock&code=${p.code}`)"
            >
              <span class="watch-item__rank">{{ i + 1 }}</span>
              <span class="watch-item__name">{{ p.name }}</span>
              <span class="watch-item__code num">{{ p.code }}</span>
              <span class="watch-item__chg num" :class="p.change_pct >= 0 ? 'up' : 'down'">{{ fmtPct(p.change_pct) }}</span>
              <span class="watch-item__score num">{{ p.score.toFixed(1) }}</span>
            </button>
          </div>
          <EmptyGuide
            v-else
            icon="picks"
            title="还没有选股结果"
            desc="运行一次多因子扫描，就能在这里看到今日候选。"
          >
            <template #action>
              <button class="ui-btn ui-btn--primary" @click="go('/trade?tab=picks')">去选股</button>
            </template>
          </EmptyGuide>
        </SectionCard>

        <!-- 市场速览 -->
        <SectionCard title="市场速览" desc="主要指数">
          <template #actions>
            <button class="ui-btn ui-btn--sm ui-btn--ghost" @click="go('/market')">
              行情<Icon name="chevron-right" :size="13" />
            </button>
          </template>
          <div v-if="data.market?.length" class="indices">
            <div v-for="idx in data.market" :key="idx.code" class="index-item">
              <div class="index-item__name">{{ idx.name }}</div>
              <div class="index-item__price num">{{ idx.price.toLocaleString() }}</div>
              <div class="index-item__chg num" :class="idx.change_pct >= 0 ? 'up' : 'down'">{{ fmtPct(idx.change_pct) }}</div>
            </div>
          </div>
          <EmptyGuide v-else icon="market" title="暂无行情数据" />
        </SectionCard>
      </div>

      <!-- 快捷流程 -->
      <SectionCard title="快捷流程" desc="常用操作一键直达">
        <div class="quick-grid">
          <button v-for="q in QUICK" :key="q.label" class="quick-item" @click="go(q.to)">
            <span class="quick-item__icon"><Icon :name="q.icon" :size="18" /></span>
            <span class="quick-item__text">
              <span class="quick-item__label">{{ q.label }}</span>
              <span class="quick-item__desc">{{ q.desc }}</span>
            </span>
            <Icon name="chevron-right" :size="14" class="quick-item__arrow" />
          </button>
        </div>
      </SectionCard>

      <p class="as-of faint">数据时间：{{ data.as_of }}</p>
    </template>
  </AppPage>
</template>

<style scoped>
.metrics {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: var(--sp-4);
  padding: var(--sp-5);
  background: var(--bg-raised);
  border: 1px solid var(--border-soft);
  border-radius: var(--radius-lg);
}
.cols {
  display: grid;
  grid-template-columns: minmax(0, 1.1fr) minmax(0, 0.9fr);
  gap: var(--section-gap);
}
@media (max-width: 1024px) { .cols { grid-template-columns: 1fr; } }

.watchlist { display: flex; flex-direction: column; }
.watch-item {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  padding: 10px var(--sp-5);
  border: 0;
  border-bottom: 1px solid var(--border-soft);
  background: transparent;
  color: var(--text);
  font-size: var(--fs-md);
  text-align: left;
  cursor: pointer;
  transition: background var(--dur-fast);
}
.watch-item:last-child { border-bottom: 0; }
.watch-item:hover { background: var(--bg-hover); }
.watch-item__rank {
  width: 20px;
  height: 20px;
  display: grid;
  place-items: center;
  border-radius: var(--radius-pill);
  background: var(--bg-overlay);
  color: var(--text-faint);
  font-size: var(--fs-xs);
  flex: none;
}
.watch-item__name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.watch-item__code { color: var(--text-faint); font-size: var(--fs-sm); }
.watch-item__chg { width: 68px; text-align: right; }
.watch-item__score { width: 44px; text-align: right; color: var(--gold); font-weight: 600; }

.indices { display: flex; flex-direction: column; }
.index-item {
  display: flex;
  align-items: baseline;
  gap: var(--sp-3);
  padding: 10px var(--sp-5);
  border-bottom: 1px solid var(--border-soft);
}
.index-item:last-child { border-bottom: 0; }
.index-item__name { flex: 1; color: var(--text-sub); font-size: var(--fs-sm); }
.index-item__price { font-size: var(--fs-lg); font-weight: 600; }
.index-item__chg { width: 72px; text-align: right; font-size: var(--fs-sm); }

.quick-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); }
.quick-item {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  padding: var(--sp-4) var(--sp-5);
  border: 0;
  border-right: 1px solid var(--border-soft);
  background: transparent;
  color: var(--text);
  text-align: left;
  cursor: pointer;
  transition: background var(--dur-fast);
}
.quick-item:last-child { border-right: 0; }
.quick-item:hover { background: var(--bg-hover); }
.quick-item__icon {
  display: grid;
  place-items: center;
  width: 38px;
  height: 38px;
  border-radius: var(--radius-md);
  background: var(--gold-dim);
  color: var(--gold);
  flex: none;
}
.quick-item__text { display: flex; flex-direction: column; gap: 2px; flex: 1; min-width: 0; }
.quick-item__label { font-size: var(--fs-md); font-weight: 600; }
.quick-item__desc { font-size: var(--fs-xs); color: var(--text-faint); }
.quick-item__arrow { color: var(--text-faint); flex: none; }
.as-of { margin: 0; font-size: var(--fs-xs); }
</style>
