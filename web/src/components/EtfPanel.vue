<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import DataTable from '@/components/ui/DataTable.vue'
import type { DataColumn } from '@/components/ui/DataTable.vue'
import SearchInput from '@/components/ui/SearchInput.vue'
import LoadingBlock from '@/components/ui/LoadingBlock.vue'
import EmptyGuide from '@/components/ui/EmptyGuide.vue'
import SegmentedControl from '@/components/ui/SegmentedControl.vue'
import KlineChart from '@/components/charts/KlineChart.vue'
import { getEtfList, getEtfKline, getEtfCompare } from '@/api'
import type { EtfRef, KlineBar, EtfCompare } from '@/api'
import { useEChart, cssVar } from '@/composables/useEChart'

const props = defineProps<{ initialCode?: string }>()

const list = ref<EtfRef[]>([])
const loading = ref(true)
const error = ref('')
const search = ref('')
const types = ref<string[]>([])
const typeFilter = ref('')

const selected = ref<EtfRef | null>(null)
const kline = ref<KlineBar[]>([])
const klineLoading = ref(false)
const days = ref('250')

const compareSel = ref<string[]>([])
const compare = ref<EtfCompare | null>(null)
const compareLoading = ref(false)

const DAY_OPTIONS = [
  { value: '60', label: '60日' },
  { value: '120', label: '120日' },
  { value: '250', label: '250日' },
  { value: '500', label: '500日' },
]

const filtered = computed(() => {
  let rows = list.value
  if (search.value) {
    const q = search.value.trim()
    rows = rows.filter((r) => r.code.includes(q) || (r.name || '').includes(q))
  }
  if (typeFilter.value) rows = rows.filter((r) => r.type === typeFilter.value)
  return rows
})

const lastBar = computed(() => kline.value[kline.value.length - 1] ?? null)
const changePct = computed(() => {
  if (!lastBar.value || kline.value.length < 2) return 0
  const prev = kline.value[kline.value.length - 2].close
  return prev ? ((lastBar.value.close - prev) / prev) * 100 : 0
})

function lwcTime(d: string): string {
  return /^\d{8}$/.test(d) ? `${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6, 8)}` : d
}
const lwcBars = computed(() =>
  kline.value.map((b) => ({
    time: lwcTime(b.date),
    open: b.open,
    high: b.high,
    low: b.low,
    close: b.close,
    volume: b.volume,
  })),
)

async function loadList() {
  loading.value = true
  error.value = ''
  try {
    list.value = await getEtfList()
    types.value = [...new Set(list.value.map((r) => r.type).filter(Boolean))].sort()
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'ETF 列表加载失败'
  } finally {
    loading.value = false
  }
}

async function open(row: EtfRef) {
  selected.value = row
  kline.value = []
  klineLoading.value = true
  try {
    kline.value = await getEtfKline(row.code, Number(days.value))
  } catch (e) {
    kline.value = []
    error.value = e instanceof Error ? e.message : 'K线加载失败'
  } finally {
    klineLoading.value = false
  }
}

async function runCompare() {
  if (compareSel.value.length < 2) return
  compareLoading.value = true
  compare.value = null
  try {
    compare.value = await getEtfCompare(compareSel.value, Number(days.value))
  } catch (e) {
    error.value = e instanceof Error ? e.message : '对比加载失败'
  } finally {
    compareLoading.value = false
  }
}

function toggleCompare(code: string) {
  const i = compareSel.value.indexOf(code)
  if (i >= 0) compareSel.value.splice(i, 1)
  else if (compareSel.value.length < 5) compareSel.value.push(code)
  if (compareSel.value.length >= 2) runCompare()
}

const compareEl = ref<HTMLElement | null>(null)
useEChart(compareEl, () => {
  const c = compare.value
  const up = cssVar('--up', '#e0483e')
  const down = cssVar('--down', '#2eb872')
  const text = cssVar('--text-sub', '#8a8f9a')
  const palette = [cssVar('--accent', '#D4A574'), up, down, cssVar('--ok', '#58c08a'), '#7d9dff']
  return {
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis' },
    legend: { data: c?.series.map((s) => s.name) ?? [], textStyle: { color: text } },
    grid: { left: 56, right: 20, top: 40, bottom: 28 },
    xAxis: {
      type: 'category',
      data: c?.dates ?? [],
      axisLabel: { color: text },
      axisLine: { lineStyle: { color: cssVar('--border', '#2a2f3a') } },
    },
    yAxis: {
      type: 'value',
      scale: true,
      axisLabel: { color: text, formatter: (v: number) => v.toFixed(2) },
      splitLine: { lineStyle: { color: cssVar('--border-soft', '#22262f') } },
    },
    series: (c?.series ?? []).map((s, i) => ({
      name: s.name,
      type: 'line' as const,
      smooth: true,
      showSymbol: false,
      data: s.values,
      lineStyle: { width: 1.6, color: palette[i % palette.length] },
      itemStyle: { color: palette[i % palette.length] },
    })),
  }
})

watch(days, () => {
  if (selected.value) open(selected.value)
  if (compareSel.value.length >= 2) runCompare()
})
watch(() => props.initialCode, (c) => {
  if (c) {
    const hit = list.value.find((r) => r.code === c)
    if (hit) open(hit)
  }
})

const columns: DataColumn[] = [
  { key: 'code', title: '代码' },
  { key: 'name', title: '名称' },
  { key: 'type', title: '类型' },
]
const klineCols: DataColumn[] = [
  {
    key: 'date',
    title: '日期',
    format: (r) => {
      const s = String(r.date || '')
      return /^\d{8}$/.test(s) ? `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)}` : s
    },
  },
  { key: 'open', title: '开盘', align: 'right', format: (r) => Number(r.open).toFixed(3) },
  { key: 'high', title: '最高', align: 'right', format: (r) => Number(r.high).toFixed(3) },
  { key: 'low', title: '最低', align: 'right', format: (r) => Number(r.low).toFixed(3) },
  { key: 'close', title: '收盘', align: 'right', format: (r) => Number(r.close).toFixed(3) },
  { key: 'volume', title: '成交量(万份)', align: 'right', format: (r) => Math.round(Number(r.volume) / 10000).toLocaleString() },
]
const klineRows = computed(() => [...kline.value].reverse() as unknown as Record<string, unknown>[])

function fmtPct(v: number) { return (v >= 0 ? '+' : '') + v.toFixed(2) + '%' }

onMounted(loadList)
</script>

<template>
  <div class="etf-panel">
    <div class="etf-cols">
      <!-- 列表 -->
      <div class="etf-list">
        <div class="etf-list__bar">
          <SearchInput v-model="search" width="100%" placeholder="搜索 ETF 名称 / 代码" />
        </div>
        <div class="etf-list__types">
          <button
            class="type-chip"
            :class="{ active: typeFilter === '' }"
            @click="typeFilter = ''"
          >全部</button>
          <button
            v-for="t in types"
            :key="t"
            class="type-chip"
            :class="{ active: typeFilter === t }"
            @click="typeFilter = t"
          >{{ t }}</button>
        </div>
        <LoadingBlock v-if="loading && !list.length" :rows="8" />
        <EmptyGuide v-else-if="error && !list.length" icon="alert" title="ETF 加载失败" :desc="error">
          <template #action><button class="ui-btn" @click="loadList">重试</button></template>
        </EmptyGuide>
        <DataTable
          v-else
          :columns="columns"
          :rows="filtered as unknown as Record<string, unknown>[]"
          row-key="code"
          compact
          :page-size="0"
          @row-click="open($event as unknown as EtfRef)"
        >
          <template #cell-name="{ row }">
            <label class="cmp" @click.stop>
              <input
                type="checkbox"
                :checked="compareSel.includes(String(row.code))"
                :disabled="compareSel.length >= 5 && !compareSel.includes(String(row.code))"
                @change="toggleCompare(String(row.code))"
              />
              <span>{{ row.name }}</span>
            </label>
          </template>
        </DataTable>
        <div v-if="compareSel.length >= 2" class="compare-hint">
          已选 {{ compareSel.length }} 只做归一化对比
          <button class="ui-btn ui-btn-sm" @click="compareSel = []">清除</button>
        </div>
      </div>

      <!-- 详情 -->
      <div class="etf-detail">
        <div class="etf-detail__bar">
          <SegmentedControl v-model="days" size="sm" :options="DAY_OPTIONS" />
        </div>

        <EmptyGuide
          v-if="!selected"
          icon="kline"
          title="选择一只 ETF"
          desc="左侧列表点击查看 K 线；勾选 2-5 只查看归一化对比。"
        />
        <LoadingBlock v-else-if="klineLoading && !kline.length" :rows="8" />
        <template v-else-if="kline.length">
          <div class="etf-head">
            <div>
              <span class="etf-head__name">{{ selected.name }}</span>
              <span class="etf-head__code num">{{ selected.code }}</span>
              <span v-if="selected.type" class="etf-head__type">{{ selected.type }}</span>
            </div>
            <div class="etf-head__quote">
              <span class="etf-head__price num">{{ lastBar?.close.toFixed(3) }}</span>
              <span class="num" :class="changePct >= 0 ? 'up' : 'down'">{{ fmtPct(changePct) }}</span>
            </div>
          </div>
          <KlineChart :bars="lwcBars" :height="380" />
          <div class="etf-table">
            <h3 class="sub-title">历史数据（近 {{ Math.min(kline.length, 30) }} 条）</h3>
            <DataTable :columns="klineCols" :rows="klineRows.slice(0, 30)" row-key="date" compact :page-size="0" />
          </div>
        </template>
        <EmptyGuide v-else icon="alert" title="该 ETF 暂无 K线数据" desc="可能尚未拉取全量历史，稍后重试。" />
      </div>
    </div>

    <!-- 对比 -->
    <div v-if="compare" class="compare-pane">
      <h3 class="sub-title">归一化对比（起始 = 1.0）</h3>
      <LoadingBlock v-if="compareLoading" :rows="4" />
      <div v-else ref="compareEl" class="compare-chart" />
    </div>
  </div>
</template>

<style scoped>
.etf-panel { display: flex; flex-direction: column; gap: var(--sp-5); }
.etf-cols {
  display: grid;
  grid-template-columns: minmax(320px, 2fr) minmax(0, 3fr);
  gap: var(--sp-5);
}
.etf-list { display: flex; flex-direction: column; gap: var(--sp-3); min-width: 0; }
.etf-list__bar { display: flex; }
.etf-list__types { display: flex; flex-wrap: wrap; gap: 6px; max-height: 64px; overflow: auto; }
.type-chip {
  padding: 2px 10px;
  font-size: var(--fs-xs);
  border-radius: 999px;
  border: 1px solid var(--border-soft);
  background: var(--bg);
  color: var(--text-sub);
  cursor: pointer;
}
.type-chip.active { border-color: var(--accent); color: var(--accent); }
.cmp { display: flex; align-items: center; gap: 6px; cursor: pointer; }
.cmp input { accent-color: var(--accent); }
.compare-hint { font-size: var(--fs-xs); color: var(--text-faint); display: flex; align-items: center; gap: var(--sp-2); }
.etf-detail { display: flex; flex-direction: column; gap: var(--sp-3); min-width: 0; }
.etf-detail__bar { display: flex; justify-content: flex-end; }
.etf-head { display: flex; align-items: flex-end; justify-content: space-between; gap: var(--sp-4); flex-wrap: wrap; }
.etf-head__name { font-size: var(--fs-xl); font-weight: 650; }
.etf-head__code { margin-left: var(--sp-2); color: var(--text-faint); font-size: var(--fs-sm); }
.etf-head__type { margin-left: var(--sp-2); font-size: var(--fs-xs); color: var(--accent); border: 1px solid var(--border-soft); border-radius: 4px; padding: 1px 6px; }
.etf-head__quote { display: flex; align-items: baseline; gap: var(--sp-3); }
.etf-head__price { font-size: var(--fs-2xl); font-weight: 700; }
.etf-table { margin-top: var(--sp-3); }
.sub-title { margin: 0 0 var(--sp-2); font-size: var(--fs-md); font-weight: 600; color: var(--text-sub); }
.compare-pane { border-top: 1px solid var(--border-soft); padding-top: var(--sp-4); }
.compare-chart { height: 320px; }
@media (max-width: 900px) {
  .etf-cols { grid-template-columns: 1fr; }
}
</style>