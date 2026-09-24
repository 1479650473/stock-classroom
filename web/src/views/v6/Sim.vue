<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import AppPage from '@/components/ui/AppPage.vue'
import SectionCard from '@/components/ui/SectionCard.vue'
import DataTable from '@/components/ui/DataTable.vue'
import type { DataColumn } from '@/components/ui/DataTable.vue'
import { getSimAccounts, refreshSim } from '@/api'
import type { SimAccount, SimTrade } from '@/api'
import { useEChart, cssVar } from '@/composables/useEChart'
import { tooltipStyle } from '@/lib/chartTheme'

const accounts = ref<SimAccount[]>([])
const dataDate = ref('')
const generated = ref('')
const loading = ref(true)
const error = ref('')
const sel = ref('')
const refreshing = ref(false)
const chartEl = ref<HTMLElement | null>(null)

const cur = computed(() => accounts.value.find((a) => a.name === sel.value) || accounts.value[0] || null)

async function load() {
  loading.value = true
  error.value = ''
  try {
    const d = await getSimAccounts()
    accounts.value = d.accounts || []
    dataDate.value = d.data_date
    generated.value = d.generated
    if (!sel.value && accounts.value.length) sel.value = accounts.value[0].name
  } catch (e) {
    error.value = String(e)
  } finally {
    loading.value = false
    await nextTick()
    setTimeout(() => drawChart(), 50)
  }
}

async function doRefresh() {
  refreshing.value = true
  try {
    const d = await refreshSim()
    accounts.value = d.accounts || []
    dataDate.value = d.data_date
    generated.value = d.generated
  } catch (e) {
    error.value = String(e)
  } finally {
    refreshing.value = false
  }
}

onMounted(load)

function fmtNum(n: number | undefined, digits = 0): string {
  if (n === undefined || n === null || !Number.isFinite(n)) return '—'
  return n.toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

// ---- 图表：全部账户收益率曲线（归一化到 0） ----
const { draw: drawChart } = useEChart(chartEl, () => {
  const colors = [
    cssVar('--up', '#e05252'), cssVar('--down', '#2ea36e'), cssVar('--accent', '#D4A574'),
    '#7C8CF8', '#E8A33D', '#9B7EDE', '#4FB3BF',
  ]
  const series = accounts.value
    .filter((a) => (a.nav_history || []).length >= 1)
    .map((a, i) => {
      const pts: [string, number][] = []
      for (const h of a.nav_history || []) {
        const dstr = h.date.length === 8
          ? `${h.date.slice(0, 4)}-${h.date.slice(4, 6)}-${h.date.slice(6, 8)}`
          : h.date
        pts.push([dstr, (h.nav / a.init - 1) * 100])
      }
      // 若最后一个点是当前估值，用最新 nav 追加
      const lastNavPct = (a.nav / a.init - 1) * 100
      if (pts.length && Math.abs(pts[pts.length - 1][1] - lastNavPct) > 0.001) {
        const today = new Date()
        const tstr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`
        pts.push([tstr, lastNavPct])
      }
      return {
        name: a.label,
        type: 'line' as const,
        smooth: true,
        symbol: 'circle',
        symbolSize: 5,
        data: pts,
        itemStyle: { color: colors[i % colors.length] },
        lineStyle: { color: colors[i % colors.length], width: 2 },
      }
    })
  return {
    animation: false,
    grid: { left: 52, right: 24, top: 36, bottom: 36 },
    tooltip: {
      trigger: 'axis',
      ...tooltipStyle(),
      valueFormatter: (v: unknown) => (v === null || v === undefined ? '—' : Number(v).toFixed(2) + '%'),
    },
    legend: { top: 4, textStyle: { color: cssVar('--text-sub', '#9AA4B2'), fontSize: 11 } },
    xAxis: {
      type: 'time',
      axisLine: { lineStyle: { color: cssVar('--border', '#2A2E37') } },
      axisLabel: { color: cssVar('--text-faint', '#6B7280'), fontSize: 10, hideOverlap: true },
    },
    yAxis: {
      type: 'value',
      scale: true,
      axisLabel: {
        color: cssVar('--text-faint', '#6B7280'),
        fontSize: 10,
        formatter: (v: number) => v.toFixed(1) + '%',
      },
      splitLine: { lineStyle: { color: cssVar('--border', '#2A2E37') } },
    },
    series,
  }
})
// 数据到达后重画曲线
watch(
  () => accounts.value.length,
  async () => {
    await nextTick()
    drawChart()
  },
)

// ---- 持仓表 ----
const posCols: DataColumn[] = [
  { key: 'code', title: '代码', width: '90px', sortable: true },
  { key: 'name', title: '名称', width: '110px' },
  { key: 'leg', title: '腿', width: '70px' },
  { key: 'shares', title: '数量', align: 'right', sortable: true, format: (r) => fmtNum(r.shares as number) },
  { key: 'cost', title: '成本', align: 'right', format: (r) => Number(r.cost).toFixed(3) },
  { key: 'price', title: '现价', align: 'right', format: (r) => Number(r.price).toFixed(3) },
  { key: 'value', title: '市值', align: 'right', sortable: true, format: (r) => fmtNum(r.value as number, 0) },
  {
    key: 'ret_pct', title: '盈亏', align: 'right', sortable: true,
    format: (r) => {
      const v = Number(r.ret_pct)
      return (v >= 0 ? '+' : '') + v.toFixed(2) + '%'
    },
    cellClass: (r) => (Number(r.ret_pct) >= 0 ? 'cell-up' : 'cell-down'),
  },
]

// ---- 交易流水 ----
const tradeCols: DataColumn[] = [
  { key: 'date', title: '日期', width: '95px' },
  { key: 'leg', title: '腿', width: '60px' },
  { key: 'code', title: '代码', width: '90px' },
  {
    key: 'side', title: '方向', width: '60px',
    format: (r) => (String(r.side).toUpperCase() === 'BUY' ? '买入' : '卖出'),
    cellClass: (r) => (String(r.side).toUpperCase() === 'BUY' ? 'cell-up' : 'cell-down'),
  },
  { key: 'shares', title: '数量', align: 'right', format: (r) => fmtNum(r.shares as number) },
  { key: 'price', title: '价格', align: 'right', format: (r) => Number(r.price).toFixed(3) },
  { key: 'amount', title: '金额', align: 'right', format: (r) => fmtNum(r.amount as number, 0) },
  { key: 'fee', title: '费用', align: 'right', format: (r) => Number(r.fee).toFixed(2) },
]

// 交易行加唯一 key
const tradeRows = computed(() =>
  (cur.value?.trades || []).map((t, i) => ({ ...t, idx: i })),
)
void tradeRows

// ---- 交易流水：按账户折叠 + 按调仓日分组 ----
const expanded = reactive<Record<string, boolean>>({})
function toggleTrades(name: string) {
  expanded[name] = !expanded[name]
}

function groupByDate(trades: SimTrade[]) {
  const m = new Map<string, Record<string, unknown>[]>()
  let i = 0
  for (const t of trades) {
    const d = String(t.date)
    if (!m.has(d)) m.set(d, [])
    m.get(d)!.push({ ...t, idx: i++ })
  }
  return [...m.entries()]
    .sort((a, b) => (a[0] < b[0] ? -1 : 1))
    .map(([date, items]) => ({
      date,
      label: date.length === 8 ? `${date.slice(0, 4)}-${date.slice(4, 6)}-${date.slice(6, 8)}` : date,
      items,
    }))
}
</script>

<template>
  <AppPage title="模拟盘" :subtitle="`对接 stock-ml 策略账户 · 数据日期 ${dataDate || '—'} · 快照 ${generated || '—'}`">
    <template #actions>
      <button class="btn" :disabled="refreshing" @click="doRefresh">
        {{ refreshing ? '刷新中…' : '刷新数据' }}
      </button>
    </template>

    <div v-if="error" class="err-box">加载失败：{{ error }}</div>

    <!-- 账户卡片 -->
    <div class="acc-grid">
      <div
        v-for="a in accounts"
        :key="a.name"
        class="acc-card"
        :class="{ active: a.name === (cur?.name || '') }"
        @click="sel = a.name"
      >
        <div class="acc-label">{{ a.label }}</div>
        <div class="acc-nav">{{ fmtNum(a.nav, 0) }}</div>
        <div class="acc-ret" :class="a.ret_pct >= 0 ? 'up' : 'down'">
          {{ a.ret_pct >= 0 ? '+' : '' }}{{ a.ret_pct.toFixed(2) }}%
        </div>
        <div class="acc-sub">{{ a.positions.length }} 持仓 · {{ a.strategy || '—' }}</div>
        <div v-if="a.legs" class="acc-legs">
          <span v-for="l in a.legs" :key="l.name">{{ l.name }} {{ fmtNum(l.nav, 0) }}</span>
        </div>
      </div>
    </div>

    <!-- 净值曲线 -->
    <SectionCard title="净值曲线" desc="各账户累计收益率（起点归一化）">
      <div ref="chartEl" style="height: 300px; width: 100%"></div>
    </SectionCard>

    <!-- 持仓 -->
    <SectionCard v-if="cur" :title="`持仓明细 · ${cur.label}`" :desc="`${cur.positions.length} 只 · 市值 ${fmtNum(cur.mv, 0)} · 现金 ${fmtNum(cur.cash, 0)}`">
      <DataTable :columns="posCols" :rows="cur.positions" row-key="code" :page-size="10" storage-key="sim-pos" />
    </SectionCard>

    <!-- 交易流水：按账户折叠 · 按调仓日分组 -->
    <SectionCard title="交易流水" desc="点击账户展开 · 按调仓日分组">
      <div v-for="a in accounts" :key="a.name" class="trade-acc">
        <div class="trade-acc-head" @click="toggleTrades(a.name)">
          <span class="caret">{{ expanded[a.name] ? '▾' : '▸' }}</span>
          <span class="trade-acc-name">{{ a.label }}</span>
          <span class="trade-acc-count">{{ (a.trades || []).length }} 笔</span>
        </div>
        <div v-if="expanded[a.name]" class="trade-acc-body">
          <div v-for="g in groupByDate(a.trades || [])" :key="g.date" class="trade-day">
            <div class="trade-day-head">{{ g.label }} · 调仓（{{ g.items.length }} 笔）</div>
            <DataTable :columns="tradeCols" :rows="g.items" row-key="idx" :page-size="0" />
          </div>
        </div>
      </div>
      <div v-if="!accounts.length" class="acc-empty">暂无账户数据</div>
    </SectionCard>
  </AppPage>
</template>

<style scoped>
.btn {
  padding: 6px 16px;
  border-radius: 8px;
  border: 1px solid var(--border-strong);
  background: var(--bg-raised);
  color: var(--text);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.15s;
}
.btn:hover:not(:disabled) {
  border-color: var(--accent);
  color: var(--accent);
}
.btn:disabled { opacity: 0.5; cursor: default; }

.acc-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}
.acc-card {
  padding: 14px 16px;
  border-radius: 12px;
  border: 1px solid var(--border-soft);
  background: linear-gradient(180deg, var(--bg-raised), var(--bg-panel));
  cursor: pointer;
  transition: border-color 0.15s, transform 0.15s;
}
.acc-card:hover { transform: translateY(-2px); border-color: var(--border-strong); }
.acc-card.active { border-color: var(--accent); }
.acc-label { font-size: 12px; color: var(--text-sub); margin-bottom: 6px; }
.acc-nav { font-size: 22px; font-weight: 600; color: var(--text); font-variant-numeric: tabular-nums; }
.acc-ret { font-size: 14px; font-weight: 600; margin-top: 2px; }
.acc-ret.up { color: var(--up); }
.acc-ret.down { color: var(--down); }
.acc-sub { font-size: 11px; color: var(--text-faint); margin-top: 6px; }
.acc-legs { display: flex; gap: 8px; font-size: 10px; color: var(--text-faint); margin-top: 4px; }

.err-box {
  padding: 10px 14px;
  border-radius: 8px;
  background: color-mix(in srgb, var(--up) 10%, transparent);
  border: 1px solid color-mix(in srgb, var(--up) 35%, transparent);
  color: var(--up);
  font-size: 13px;
  margin-bottom: 14px;
}

/* ---- 交易流水折叠区（按账户） ---- */
.trade-acc {
  border: 1px solid var(--border-soft);
  border-radius: 10px;
  margin-bottom: 10px;
  overflow: hidden;
}
.trade-acc-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  cursor: pointer;
  background: var(--bg-raised);
  transition: background 0.15s;
}
.trade-acc-head:hover { background: var(--bg-hover); }
.trade-acc-head .caret { color: var(--accent); font-size: 12px; width: 14px; }
.trade-acc-name { font-size: 14px; font-weight: 600; color: var(--text); }
.trade-acc-count { font-size: 12px; color: var(--text-faint); margin-left: auto; }
.trade-acc-body { padding: 10px 12px; }
.trade-day { margin-bottom: 14px; }
.trade-day:last-child { margin-bottom: 2px; }
.trade-day-head {
  font-size: 12px;
  font-weight: 600;
  color: var(--accent);
  padding: 4px 0 8px 2px;
  border-bottom: 1px dashed var(--border);
  margin-bottom: 8px;
}
.acc-empty { padding: 16px; text-align: center; color: var(--text-faint); font-size: 13px; }
</style>
