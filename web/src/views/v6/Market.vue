<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppPage from '@/components/ui/AppPage.vue'
import PageToolbar from '@/components/ui/PageToolbar.vue'
import SectionCard from '@/components/ui/SectionCard.vue'
import DataTable from '@/components/ui/DataTable.vue'
import type { DataColumn } from '@/components/ui/DataTable.vue'
import SearchInput from '@/components/ui/SearchInput.vue'
import EmptyGuide from '@/components/ui/EmptyGuide.vue'
import LoadingBlock from '@/components/ui/LoadingBlock.vue'
import SegmentedControl from '@/components/ui/SegmentedControl.vue'
import KlineChart from '@/components/charts/KlineChart.vue'
import EtfPanel from '@/components/EtfPanel.vue'
import Icon from '@/components/Icon.vue'
import { getIndices, getSectors, getNorthFlow, getKline, searchStock, getFundFlow } from '@/api'
import type { IndexQuote, KlineBar, StockRef, FundFlowBar } from '@/api'
import { usePersistedRef } from '@/composables/usePersistedRef'

type Tab = 'market' | 'stock' | 'etf'

const route = useRoute()
const router = useRouter()

const TABS = [
  { value: 'market', label: '市场', icon: 'market' },
  { value: 'stock', label: '个股', icon: 'kline' },
  { value: 'etf', label: 'ETF', icon: 'kline' },
]

const tab = ref<Tab>(route.query.tab === 'stock' ? 'stock' : route.query.tab === 'etf' ? 'etf' : 'market')
// 记住上次查看的股票与周期，下次打开自动恢复
const code = usePersistedRef('market.code', String(route.query.code || ''))
const stockName = ref(String(route.query.name || ''))
const days = usePersistedRef('market.days', '250')

const indices = ref<IndexQuote[]>([])
const sectors = ref<Record<string, unknown>[]>([])
const north = ref<Record<string, unknown>[]>([])
const marketLoading = ref(true)
const marketError = ref('')

const kline = ref<KlineBar[]>([])
const klineLoading = ref(false)
const klineError = ref('')
const fundFlow = ref<FundFlowBar[]>([])

const lastBar = computed(() => kline.value[kline.value.length - 1] ?? null)

/** 资金流副图数据(主力净流入, 与K线时间对齐) */
const lwcFundFlow = computed(() =>
  fundFlow.value.map((f) => ({
    time: lwcTime(f.date),
    mainNet: f.main_net,
    mainRatio: f.main_ratio,
  })),
)

/** YYYYMMDD -> YYYY-MM-DD (lightweight-charts 要求) */
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
const changePct = computed(() => {
  if (!lastBar.value || kline.value.length < 2) return 0
  const prev = kline.value[kline.value.length - 2].close
  return prev ? ((lastBar.value.close - prev) / prev) * 100 : 0
})

const DAY_OPTIONS = [
  { value: '60', label: '60日' },
  { value: '120', label: '120日' },
  { value: '250', label: '250日' },
  { value: '500', label: '500日' },
]

async function loadMarket() {
  marketLoading.value = true
  marketError.value = ''
  try {
    const [i, s, n] = await Promise.all([getIndices(), getSectors('industry'), getNorthFlow(30)])
    indices.value = i
    sectors.value = s
    north.value = n
  } catch (e) {
    marketError.value = e instanceof Error ? e.message : '市场数据加载失败'
  } finally {
    marketLoading.value = false
  }
}

async function loadKline() {
  if (!code.value) return
  klineLoading.value = true
  klineError.value = ''
  try {
    const [bars, ff] = await Promise.all([
      getKline(code.value, Number(days.value)),
      getFundFlow(code.value, Number(days.value)).catch(() => [] as FundFlowBar[]),
    ])
    kline.value = bars
    fundFlow.value = ff
  } catch (e) {
    klineError.value = e instanceof Error ? e.message : 'K线加载失败'
    kline.value = []
  } finally {
    klineLoading.value = false
  }
}

function onPick(s: StockRef) {
  code.value = s.code
  stockName.value = s.name
  tab.value = 'stock'
  loadKline()
}

async function resolveStockName() {
  if (!code.value || stockName.value) return
  try {
    const rows = await searchStock(code.value)
    const hit = rows.find((r) => r.code === code.value)
    if (hit?.name) stockName.value = hit.name
  } catch {
    /* 名称解析失败不影响 K 线展示 */
  }
}

function onSubmit(c: string) {
  if (!c) return
  code.value = c
  tab.value = 'stock'
  loadKline()
}

watch(tab, (v) => {
  router.replace({ query: { ...route.query, tab: v } })
})
watch(days, () => { if (code.value) loadKline() })
watch(
  () => route.query,
  (q) => {
    if (q.tab === 'stock' && tab.value !== 'stock') tab.value = 'stock'
    if (q.code && String(q.code) !== code.value) {
      code.value = String(q.code)
      stockName.value = String(q.name || '')
      tab.value = 'stock'
      loadKline()
      resolveStockName()
    }
  },
)

function fmtPct(v: number) { return (v >= 0 ? '+' : '') + v.toFixed(2) + '%' }
function fmtNum(v: number) {
  const n = Math.abs(v) < 0.005 ? 0 : v
  return n.toFixed(2)
}

const sectorColumns: DataColumn[] = [
  { key: 'name', title: '板块' },
  { key: 'change_pct', title: '涨跌幅', align: 'right', sortable: true },
]

const northColumns: DataColumn[] = [
  { key: 'date', title: '日期' },
  { key: 'net_flow', title: '净流入（亿）', align: 'right', sortable: true },
]

const klineColumns: DataColumn[] = [
  {
    key: 'date',
    title: '日期',
    format: (r) => {
      const s = String(r.date || '')
      return /^\d{8}$/.test(s) ? `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)}` : s
    },
  },
  { key: 'open', title: '开盘', align: 'right', format: (r) => Number(r.open).toFixed(2) },
  { key: 'high', title: '最高', align: 'right', format: (r) => Number(r.high).toFixed(2) },
  { key: 'low', title: '最低', align: 'right', format: (r) => Number(r.low).toFixed(2) },
  { key: 'close', title: '收盘', align: 'right', format: (r) => Number(r.close).toFixed(2) },
  { key: 'volume', title: '成交量', align: 'right', format: (r) => Number(r.volume).toLocaleString() },
]

const klineRows = computed(() => [...kline.value].reverse() as unknown as Record<string, unknown>[])

onMounted(() => {
  loadMarket()
  if (code.value) {
    loadKline()
    resolveStockName()
  }
})
</script>

<template>
  <AppPage title="行情" subtitle="市场全景与个股技术分析">
    <template #actions>
      <SearchInput
        v-model="code"
        width="260px"
        placeholder="搜索股票 / 代码"
        @select="onPick"
        @submit="onSubmit"
      />
    </template>

    <SectionCard :padded="false">
      <div style="padding: 0 var(--sp-5)">
        <PageToolbar v-model="tab" :tabs="TABS">
          <template #extra>
            <SegmentedControl
              v-if="tab === 'stock'"
              v-model="days"
              size="sm"
              :options="DAY_OPTIONS"
            />
          </template>
        </PageToolbar>
      </div>

      <!-- 市场 -->
      <div v-if="tab === 'market'" class="pane">
        <LoadingBlock v-if="marketLoading && !indices.length" :rows="6" />
        <EmptyGuide v-else-if="marketError && !indices.length" icon="alert" title="市场数据加载失败" :desc="marketError">
          <template #action><button class="ui-btn" @click="loadMarket">重试</button></template>
        </EmptyGuide>
        <template v-else>
          <div class="indices">
            <div v-for="idx in indices" :key="idx.code" class="index-card">
              <div class="index-card__name">{{ idx.name }}</div>
              <div class="index-card__price num">{{ idx.price.toLocaleString() }}</div>
              <div class="index-card__chg num" :class="idx.change_pct >= 0 ? 'up' : 'down'">
                {{ fmtPct(idx.change_pct) }}
              </div>
            </div>
          </div>

          <div class="market-cols">
            <div>
              <h3 class="sub-title">行业板块</h3>
              <DataTable
                :columns="sectorColumns"
                :rows="sectors.slice(0, 30)"
                row-key="name"
                compact
                :page-size="0"
              >
                <template #cell-change_pct="{ row }">
                  <span :class="Number(row.change_pct) >= 0 ? 'up' : 'down'">
                    {{ fmtPct(Number(row.change_pct)) }}
                  </span>
                </template>
              </DataTable>
            </div>
            <div>
              <h3 class="sub-title">北向资金（历史，2024-08 后停更）</h3>
              <DataTable
                :columns="northColumns"
                :rows="north.slice(0, 15)"
                row-key="date"
                compact
                :page-size="0"
              >
                <template #cell-net_flow="{ row }">
                  <span :class="Number(row.net_flow) >= 0 ? 'up' : 'down'">
                    {{ fmtNum(Number(row.net_flow)) }}
                  </span>
                </template>
              </DataTable>
            </div>
          </div>
        </template>
      </div>

      <!-- 个股 -->
      <div v-else-if="tab === 'stock'" class="pane">
        <EmptyGuide
          v-if="!code && !kline.length"
          icon="kline"
          title="搜索一只股票查看 K 线"
          desc="在右上角输入代码或名称，支持键盘上下选择。"
        />
        <LoadingBlock v-else-if="klineLoading && !kline.length" :rows="8" />
        <EmptyGuide v-else-if="klineError && !kline.length" icon="alert" title="K线加载失败" :desc="klineError">
          <template #action><button class="ui-btn" @click="loadKline">重试</button></template>
        </EmptyGuide>
        <template v-else-if="kline.length">
          <div class="stock-head">
            <div>
              <span class="stock-head__name">{{ stockName || code }}</span>
              <span v-if="stockName && stockName !== code" class="stock-head__code num">{{ code }}</span>
            </div>
            <div class="stock-head__quote">
              <span class="stock-head__price num">{{ lastBar?.close.toFixed(2) }}</span>
              <span class="num" :class="changePct >= 0 ? 'up' : 'down'">{{ fmtPct(changePct) }}</span>
            </div>
          </div>
          <KlineChart :bars="lwcBars" :height="460" :fund-flow="lwcFundFlow" />
          <div class="detail-table">
            <h3 class="sub-title">历史数据（近 {{ Math.min(kline.length, 60) }} 条）</h3>
            <DataTable
              :columns="klineColumns"
              :rows="klineRows.slice(0, 60)"
              row-key="date"
              compact
              :page-size="20"
            />
          </div>
        </template>
      </div>

      <!-- ETF -->
      <div v-else-if="tab === 'etf'" class="pane">
        <EtfPanel />
      </div>
    </SectionCard>
  </AppPage>
</template>

<style scoped>
.pane { padding: var(--sp-5); }
.indices {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  gap: var(--sp-3);
  margin-bottom: var(--sp-5);
}
.index-card {
  padding: var(--sp-4);
  background: linear-gradient(180deg, var(--bg-raised), var(--bg));
  border: 1px solid var(--border-soft);
  border-radius: var(--radius-md);
  box-shadow: inset 0 1px 0 var(--sheen);
  transition: border-color var(--dur-fast) var(--ease), transform var(--dur-fast) var(--ease),
    box-shadow var(--dur-fast) var(--ease);
}
.index-card:hover {
  border-color: var(--border-strong);
  transform: translateY(-2px);
  box-shadow: inset 0 1px 0 var(--sheen), var(--shadow-lift);
}
.index-card__name { font-size: var(--fs-sm); color: var(--text-sub); }
.index-card__price { font-size: var(--fs-xl); font-weight: 700; margin: 2px 0; }
.index-card__chg { font-size: var(--fs-md); font-weight: 500; }
.market-cols {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: var(--sp-5);
}
.quoted-sub-title-disabled {
  margin: 0 0 var(--sp-2);
  font-size: var(--fs-md);
  font-weight: 600;
  color: var(--text-sub);
}
.stock-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--sp-4);
  margin-bottom: var(--sp-3);
  flex-wrap: wrap;
}
.stock-head__name { font-size: var(--fs-xl); font-weight: 650; }
.stock-head__code { margin-left: var(--sp-2); color: var(--text-faint); font-size: var(--fs-sm); }
.stock-head__quote { display: flex; align-items: baseline; gap: var(--sp-3); }
.stock-head__price { font-size: var(--fs-2xl); font-weight: 700; }
.detail-table { margin-top: var(--sp-5); }
</style>
