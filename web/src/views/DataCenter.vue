<script setup lang="ts">
import { onMounted, ref } from 'vue'
import PageHeader from '@/components/PageHeader.vue'
import Card from '@/components/Card.vue'
import StatCard from '@/components/StatCard.vue'
import Skeleton from '@/components/Skeleton.vue'
import { getBootstrap } from '@/api'
import type { Bootstrap } from '@/api'

const b = ref<Bootstrap | null>(null)
const loading = ref(true)

onMounted(async () => {
  try { b.value = await getBootstrap() } finally { loading.value = false }
})

function fmtRows(n: number) {
  if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M'
  if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K'
  return String(n)
}
</script>

<template>
  <div>
    <PageHeader title="数据中心" subtitle="数据库状态与数据统计" />
    <Skeleton v-if="loading && !b" />
    <div v-if="b" class="stats">
      <StatCard label="K线数据库" :value="b.kline.exists ? fmtRows(b.kline.rows) : '—'" icon="datacenter" :trend-value="b.kline.max ? '截至 ' + b.kline.max : '未初始化'" />
      <StatCard label="股票数量" :value="fmtRows(b.stock_list_rows)" icon="layers" />
      <StatCard label="基本面" :value="b.fundamental.exists ? fmtRows(b.fundamental.rows) : '—'" icon="database" />
      <StatCard label="缓存" :value="b.cache.exists ? fmtRows(b.cache.rows) : '—'" icon="refresh" />
    </div>
    <Card v-if="b && b.needs_init" class="mt">
      <div class="init-hint">
        <span class="muted">首次运行需要初始化数据，请点击数据管道执行初始化更新。</span>
      </div>
    </Card>
  </div>
</template>

<style scoped>
.stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: var(--sp-3); }
.mt { margin-top: var(--sp-4); }
.init-hint { padding: var(--sp-2); }
.muted { color: var(--text-sub); font-size: var(--fs-sm); }
</style>
