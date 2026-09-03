<script setup lang="ts">
import { onMounted, ref } from 'vue'
import PageHeader from '@/components/PageHeader.vue'
import Card from '@/components/Card.vue'
import Skeleton from '@/components/Skeleton.vue'
import EmptyState from '@/components/EmptyState.vue'
import { getIndices, getSectors, getNorthFlow } from '@/api'
import type { IndexQuote } from '@/api'

const indices = ref<IndexQuote[]>([])
const sectors = ref<Record<string, unknown>[]>([])
const north = ref<Record<string, unknown>[]>([])
const loading = ref(true)
const error = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [i, s, n] = await Promise.all([getIndices(), getSectors('industry'), getNorthFlow(30)])
    indices.value = i
    sectors.value = s
    north.value = n
  } catch (e) {
    error.value = e instanceof Error ? e.message : '市场数据加载失败'
  } finally {
    loading.value = false
  }
}
onMounted(load)

function fmtPct(v: number) { return (v >= 0 ? '+' : '') + v.toFixed(2) + '%' }
</script>

<template>
  <div class="market">
    <PageHeader title="看盘" subtitle="实时市场概览" />

    <Skeleton v-if="loading && !indices.length" />

    <EmptyState v-if="error && !indices.length" :message="error">
      <template #action>
        <button class="retry" @click="load">重试</button>
      </template>
    </EmptyState>

    <!-- indices -->
    <section class="sec" v-if="indices.length">
      <h2 class="sec-title">主要指数</h2>
      <div class="idx-grid">
        <Card v-for="idx in indices" :key="idx.code" padding highlight>
          <div class="idx-name">{{ idx.name }}</div>
          <div class="idx-price num">{{ idx.price.toLocaleString() }}</div>
          <div class="idx-chg num" :class="idx.change_pct >= 0 ? 'up' : 'down'">
            {{ fmtPct(idx.change_pct) }}
          </div>
        </Card>
      </div>
    </section>

    <!-- sectors top/bottom -->
    <section class="sec" v-if="sectors.length">
      <h2 class="sec-title">行业板块</h2>
      <div class="sector-grid">
        <Card v-for="s in sectors.slice(0, 20)" :key="(s.name as string)" padding>
          <div class="sec-name">{{ s.name }}</div>
          <div class="sec-val num" :class="(s.change_pct as number) >= 0 ? 'up' : 'down'">
            {{ fmtPct(s.change_pct as number) }}
          </div>
        </Card>
      </div>
    </section>

    <!-- north flow -->
    <section class="sec" v-if="north.length">
      <h2 class="sec-title">北向资金（近30日）</h2>
      <Card padding>
        <table class="mini-table">
          <thead><tr><th>日期</th><th class="ar">净流入（亿）</th></tr></thead>
          <tbody>
            <tr v-for="(r, i) in north.slice(0, 15)" :key="i">
              <td>{{ r.date }}</td>
              <td class="ar num" :class="(r.net_flow as number) >= 0 ? 'up' : 'down'">
                {{ ((r.net_flow as number) / 1e8).toFixed(2) }}
              </td>
            </tr>
          </tbody>
        </table>
      </Card>
    </section>
  </div>
</template>

<style scoped>
.market { max-width: 1100px; }
.sec { margin-bottom: var(--sp-6); }
.sec-title { font-size: var(--fs-lg); font-weight: 600; color: var(--text); margin: 0 0 var(--sp-4); }
.idx-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: var(--sp-3); }
.idx-name { font-size: var(--fs-sm); color: var(--text-sub); margin-bottom: 2px; }
.idx-price { font-size: var(--fs-xl); font-weight: 700; }
.idx-chg { font-size: var(--fs-md); font-weight: 500; }
.sector-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: var(--sp-2); }
.sec-name { font-size: var(--fs-sm); color: var(--text-sub); margin-bottom: 2px; }
.sec-val { font-size: var(--fs-md); font-weight: 600; }
.up { color: var(--up); } .down { color: var(--down); }
.mini-table { width: 100%; border-collapse: collapse; font-size: var(--fs-sm); }
.mini-table th { padding: 8px var(--sp-3); text-align: left; color: var(--text-sub); border-bottom: 1px solid var(--border); }
.mini-table .ar { text-align: right; }
.mini-table td { padding: 8px var(--sp-3); border-bottom: 1px solid var(--border-soft); color: var(--text); }
.retry {
  padding: 8px 16px; border: 1px solid var(--border); border-radius: var(--radius-sm);
  background: var(--bg-raised); color: var(--text-sub); font-size: var(--fs-sm); cursor: pointer;
}
.retry:hover { border-color: var(--gold); color: var(--gold); }
</style>
