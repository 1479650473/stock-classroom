<script setup lang="ts">
import { onMounted, ref } from 'vue'
import PageHeader from '@/components/PageHeader.vue'
import Card from '@/components/Card.vue'
import Skeleton from '@/components/Skeleton.vue'
import Icon from '@/components/Icon.vue'
import { getPicks } from '@/api'
import type { PickItem } from '@/api'

const items = ref<PickItem[]>([])
const loading = ref(true)
const stale = ref(false)

onMounted(async () => {
  try {
    const d = await getPicks(20)
    items.value = d.items
    stale.value = d.stale
  } finally {
    loading.value = false
  }
})

function fmtPct(v: number) { return (v >= 0 ? '+' : '') + v.toFixed(2) + '%' }
</script>

<template>
  <div>
    <PageHeader title="选股" subtitle="多因子评分 Top 20">
      <template #right>
        <span v-if="stale" class="tag">缓存 · 可刷新</span>
      </template>
    </PageHeader>

    <Skeleton v-if="loading && !items.length" />

    <Card v-if="items.length">
      <table class="tbl">
        <thead>
          <tr>
            <th>#</th><th>代码</th><th>名称</th><th class="ar">现价</th><th class="ar">涨跌</th><th class="ar">评分</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(p, i) in items" :key="p.code">
            <td class="muted">{{ i + 1 }}</td>
            <td class="code num">{{ p.code }}</td>
            <td>{{ p.name }}</td>
            <td class="ar num">{{ p.price.toFixed(2) }}</td>
            <td class="ar num" :class="p.change_pct >= 0 ? 'up' : 'down'">{{ fmtPct(p.change_pct) }}</td>
            <td class="ar num gold">{{ p.score.toFixed(1) }}</td>
          </tr>
        </tbody>
      </table>
    </Card>
  </div>
</template>

<style scoped>
.tbl { width: 100%; border-collapse: collapse; font-size: var(--fs-sm); }
.tbl th { padding: 10px var(--sp-3); text-align: left; color: var(--text-sub); border-bottom: 1px solid var(--border); }
.tbl .ar { text-align: right; }
.tbl tr:hover { background: var(--bg-hover); }
.tbl td { padding: 10px var(--sp-3); border-bottom: 1px solid var(--border-soft); color: var(--text); }
.code { font-family: var(--font-mono); }
.up { color: var(--up); } .down { color: var(--down); }
.gold { color: var(--gold); font-weight: 700; }
.muted { color: var(--text-faint); }
.tag { font-size: var(--fs-xs); color: var(--text-faint); border: 1px solid var(--border); padding: 2px 8px; border-radius: var(--radius-pill); }
</style>
