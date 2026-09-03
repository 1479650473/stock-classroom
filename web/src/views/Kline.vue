<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import PageHeader from '@/components/PageHeader.vue'
import Card from '@/components/Card.vue'
import KlineChart from '@/components/KlineChart.vue'
import EmptyState from '@/components/EmptyState.vue'
import Skeleton from '@/components/Skeleton.vue'
import { getKline } from '@/api'
import type { KlineBar } from '@/api'

const route = useRoute()
const code = ref((route.query.code as string) || '')
const name = ref((route.query.name as string) || '')
const bars = ref<KlineBar[]>([])
const loading = ref(false)
const loadError = ref('')
const days = ref(250)

async function load() {
  if (!code.value) return
  loading.value = true
  loadError.value = ''
  try {
    bars.value = await getKline(code.value, days.value)
  } catch (e) {
    bars.value = []
    loadError.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
}

onMounted(load)
watch(() => [route.query.code, route.query.name], ([c, n]) => {
  if (c) { code.value = c as string; name.value = (n as string) || ''; load() }
})

function fmtPct(v: number) { return (v >= 0 ? '+' : '') + v.toFixed(2) + '%' }
</script>

<template>
  <div>
    <PageHeader :title="name ? `K线 · ${name} ${code}` : code ? `K线 · ${code}` : 'K线'" subtitle="技术分析与图表">
      <template #right>
        <div class="hdr-actions">
          <select v-model="days" class="sel" @change="load">
            <option :value="60">60日</option>
            <option :value="120">120日</option>
            <option :value="250">250日</option>
            <option :value="500">500日</option>
          </select>
          <input v-model="code" class="code-input" placeholder="股票代码" @keyup.enter="load" />
        </div>
      </template>
    </PageHeader>

    <Skeleton v-if="loading && !bars.length" />

    <EmptyState v-if="!code" message="输入股票代码查看K线图" />
    <EmptyState v-if="code && loadError" :message="loadError" />

    <template v-if="code && bars.length">
      <KlineChart :bars="bars" />

      <Card class="mt" v-if="bars.length">
        <table class="tbl">
          <thead>
            <tr>
              <th>日期</th>
              <th class="ar">开盘</th>
              <th class="ar">最高</th>
              <th class="ar">最低</th>
              <th class="ar">收盘</th>
              <th class="ar">成交量</th>
              <th class="ar">涨跌</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="b in bars.slice(-30).reverse()" :key="b.date">
              <td>{{ b.date }}</td>
              <td class="ar num">{{ b.open.toFixed(2) }}</td>
              <td class="ar num">{{ b.high.toFixed(2) }}</td>
              <td class="ar num">{{ b.low.toFixed(2) }}</td>
              <td class="ar num">{{ b.close.toFixed(2) }}</td>
              <td class="ar num muted">{{ (b.volume / 10000).toFixed(0) }}万</td>
              <td class="ar num" :class="b.close >= b.open ? 'up' : 'down'">
                {{ fmtPct(((b.close - b.open) / b.open) * 100) }}
              </td>
            </tr>
          </tbody>
        </table>
      </Card>
    </template>
  </div>
</template>

<style scoped>
.hdr-actions { display: flex; gap: var(--sp-2); align-items: center; }
.code-input, .sel {
  background: var(--bg); border: 1px solid var(--border); border-radius: var(--radius-sm);
  padding: 6px 10px; color: var(--text); font-size: var(--fs-sm);
  font-family: var(--font-mono);
}
.code-input { width: 110px; }
.code-input:focus, .sel:focus { border-color: var(--gold); outline: none; }
.mt { margin-top: var(--sp-4); }
.tbl { width: 100%; border-collapse: collapse; font-size: var(--fs-sm); }
.tbl th { padding: 8px var(--sp-3); text-align: left; color: var(--text-sub); border-bottom: 1px solid var(--border); }
.tbl .ar { text-align: right; }
.tbl tr:hover { background: var(--bg-hover); }
.tbl td { padding: 8px var(--sp-3); border-bottom: 1px solid var(--border-soft); color: var(--text); }
.muted { color: var(--text-faint); }
.up { color: var(--up); } .down { color: var(--down); }
</style>
