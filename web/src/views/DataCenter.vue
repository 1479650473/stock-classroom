<script setup lang="ts">
import { onMounted, ref, computed } from 'vue'
import PageHeader from '@/components/PageHeader.vue'
import Card from '@/components/Card.vue'
import StatCard from '@/components/StatCard.vue'
import Skeleton from '@/components/Skeleton.vue'
import EmptyState from '@/components/EmptyState.vue'
import Icon from '@/components/Icon.vue'
import { getBootstrap, getPipelineStats } from '@/api'
import type { Bootstrap, PipelineStats } from '@/api'

const b = ref<Bootstrap | null>(null)
const stats = ref<PipelineStats | null>(null)
const loading = ref(true)
const error = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [boot, st] = await Promise.all([getBootstrap(), getPipelineStats()])
    b.value = boot
    stats.value = st
  } catch (e) {
    error.value = e instanceof Error ? e.message : '数据中心加载失败'
  } finally { loading.value = false }
}
onMounted(load)

function fmtRows(n: number | null | undefined) {
  if (n == null) return '—'
  if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M'
  if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K'
  return String(n)
}
function fmtDate(d: string | null | undefined) { return d ? d.slice(0, 10) : '—' }

// 各业务库表(带中文名)
const TABLES = [
  { key: 'stock_list', label: '股票列表', icon: 'layers' },
  { key: 'sector_board', label: '行业板块', icon: 'market' },
  { key: 'stock_sector', label: '板块成分', icon: 'activity' },
  { key: 'north_flow', label: '北向资金', icon: 'activity' },
  { key: 'limit_up', label: '涨停板', icon: 'arrow-up-right' },
  { key: 'fund_flow', label: '资金流向', icon: 'flow' },
  { key: 'high_low', label: '新高新低', icon: 'activity' },
  { key: 'lhb_daily', label: '龙虎榜', icon: 'info' },
  { key: 'chip_distribution', label: '筹码分布', icon: 'dot' },
]
const tableRows = computed(() => {
  const tables = stats.value?.tables
  if (!tables) return []
  return TABLES.map((t) => ({ ...t, ...(tables[t.key] ?? { rows: null, latest: null }) }))
})
</script>

<template>
  <div>
    <PageHeader title="数据中心" subtitle="数据库状态 · 各业务库统计" />

    <Skeleton v-if="loading && !b" />

    <EmptyState v-if="error && !stats" :message="error">
      <template #action>
        <button class="retry" @click="load">重试</button>
      </template>
    </EmptyState>

    <div v-if="stats" class="stats">
      <StatCard label="K线数据库" :value="fmtRows(stats.kline_rows)" icon="datacenter" :trend-value="fmtDate(stats.latest_date)" />
      <StatCard label="股票数量" :value="fmtRows(stats.stock_count)" icon="layers" :trend-value="stats.active_stocks + ' 活跃'" />
      <StatCard label="数据库大小" :value="stats.db_size" icon="database" />
      <StatCard label="基本面" :value="b?.fundamental.exists ? fmtRows(b.fundamental.rows) : '—'" icon="database" />
    </div>

    <!-- 各业务库分层 -->
    <Card class="mt" v-if="tableRows.length">
      <template #header><span class="card-title">各业务库数据</span></template>
      <table class="tbl">
        <thead>
          <tr><th>数据表</th><th class="ar">行数</th><th class="ar">最新日期</th></tr>
        </thead>
        <tbody>
          <tr v-for="t in tableRows" :key="t.key">
            <td class="tbl-name"><Icon :name="t.icon" :size="14" /> {{ t.label }}</td>
            <td class="ar num">{{ fmtRows(t.rows) }}</td>
            <td class="ar muted">{{ fmtDate(t.latest) }}</td>
          </tr>
        </tbody>
      </table>
    </Card>

    <Card v-if="b && b.needs_init" class="mt">
      <div class="init-hint">
        <span class="muted">首次运行需要初始化数据，请到「数据管道」执行初始化更新。</span>
      </div>
    </Card>
  </div>
</template>

<style scoped>
.stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: var(--sp-3); }
.mt { margin-top: var(--sp-4); }
.card-title { font-weight: 600; }
.tbl { width: 100%; border-collapse: collapse; font-size: var(--fs-sm); }
.tbl th { padding: 10px var(--sp-3); text-align: left; color: var(--text-sub); border-bottom: 1px solid var(--border); }
.tbl .ar { text-align: right; }
.tbl tr:hover { background: var(--bg-hover); }
.tbl td { padding: 9px var(--sp-3); border-bottom: 1px solid var(--border-soft); color: var(--text); }
.tbl-name { display: inline-flex; align-items: center; gap: 6px; }
.num { font-family: var(--font-mono); }
.muted { color: var(--text-faint); font-size: var(--fs-xs); }
.init-hint { padding: var(--sp-2); color: var(--text-sub); }
.retry {
  padding: 8px 16px; border: 1px solid var(--border); border-radius: var(--radius-sm);
  background: var(--bg-raised); color: var(--text-sub); font-size: var(--fs-sm); cursor: pointer;
}
.retry:hover { border-color: var(--gold); color: var(--gold); }
</style>
