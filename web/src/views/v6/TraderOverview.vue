<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import SectionCard from '@/components/ui/SectionCard.vue'
import StatTile from '@/components/ui/StatTile.vue'
import EmptyGuide from '@/components/ui/EmptyGuide.vue'
import LoadingBlock from '@/components/ui/LoadingBlock.vue'
import { useEChart, cssVar } from '@/composables/useEChart'
import { areaLineStyle, tooltipStyle } from '@/lib/chartTheme'
import { getTraderOverview } from '@/api'
import type { TraderOverview } from '@/api'

echarts.use([LineChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

const emit = defineEmits<{ select: [id: number] }>()

const data = ref<TraderOverview | null>(null)
const loading = ref(true)
const error = ref('')
const el = ref<HTMLElement | null>(null)

const COLORS = ['#D4A574', '#6EA8FE', '#7FD48C', '#E58FB1', '#B39DDB', '#FFB74D', '#80CBC4', '#F48FB1']
const BENCH_COLOR = '#9AA4B2'
const RANGES = [
  { v: 30, l: '近1月' }, { v: 90, l: '近3月' }, { v: 180, l: '近6月' },
  { v: 365, l: '近1年' }, { v: 0, l: '全部' },
]
const range = ref(0)

async function load() {
  loading.value = true
  try {
    data.value = await getTraderOverview()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
}
onMounted(load)
watch([data, range], async () => { await nextTick(); chart.draw() })

function cutoff(): string {
  if (!range.value) return ''
  const d = new Date()
  d.setDate(d.getDate() - range.value)
  return d.toISOString().slice(0, 10)
}

/** 取区间内的点，并以区间首个值为基准归一化 */
function norm(pts: { date: string; v: number }[]): [string, number][] {
  const c = cutoff()
  const inRange = c ? pts.filter((p) => p.date >= c) : pts
  if (!inRange.length) return []
  const base = inRange[0].v || 1
  return inRange.map((p) => [p.date, Number((p.v / base).toFixed(5))])
}

const series = computed(() => {
  const d = data.value
  if (!d) return []
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const out: any[] = []
  d.traders.forEach((t, i) => {
    const color = COLORS[i % COLORS.length]
    out.push({
      name: t.name,
      type: 'line',
      ...areaLineStyle(color, 2, i === 0 ? 0.26 : 0.1),   // 第一只给明显渐变，其余淡一些
      data: norm(t.nav.map((p) => ({ date: p.date, v: p.nav }))),
    })
  })
  if (d.benchmark?.dates?.length && d.benchmark.values?.length) {
    out.push({
      name: d.benchmark.name || '沪深300',
      type: 'line',
      showSymbol: false,
      smooth: true,
      lineStyle: { width: 1.5, type: 'dashed' },
      itemStyle: { color: BENCH_COLOR },
      data: norm(d.benchmark.dates.map((dd, i) => ({ date: dd, v: d.benchmark.values[i] }))),
    })
  }
  return out
})

const chart = useEChart(el, () => ({
  animation: false,
  grid: { left: 48, right: 20, top: 36, bottom: 40 },
  tooltip: {
    trigger: 'axis',
    ...tooltipStyle(),
    valueFormatter: (v: unknown) => (v === null || v === undefined ? '—' : (Number(v) * 100).toFixed(2) + '%'),
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
      formatter: (v: number) => (v * 100).toFixed(0) + '%',
    },
    splitLine: { lineStyle: { color: cssVar('--border', '#2A2E37') } },
  },
  series: series.value,
}))

const stats = computed(() => {
  const d = data.value
  if (!d) return []
  return d.traders.map((t, i) => {
    const navs = t.nav || []
    const first = navs[0]?.nav
    const last = navs[navs.length - 1]?.nav
    return {
      id: t.profile_id,
      name: t.name,
      model: t.model || '全局',
      enabled: !!t.enabled,
      total_assets: t.summary?.total_assets,
      profit_pct: t.summary?.total_profit_pct,
      nav_pct: first && last ? (last - first) * 100 : null,
      positions: t.summary?.positions,
      trades: t.summary?.total_trades,
      days: navs.length,
      color: COLORS[i % COLORS.length],
    }
  })
})

function fmtMoney(v?: number | null) {
  if (v == null) return '—'
  const abs = Math.abs(v)
  if (abs >= 1e8) return (v / 1e8).toFixed(2) + '亿'
  if (abs >= 1e4) return (v / 1e4).toFixed(2) + '万'
  return v.toLocaleString(undefined, { maximumFractionDigits: 2 })
}
function fmtPct(v?: number | null) {
  if (v == null) return '—'
  return (v >= 0 ? '+' : '') + v.toFixed(2) + '%'
}

defineExpose({ reload: load })
</script>

<template>
  <div class="overview">
    <LoadingBlock v-if="loading && !data" :rows="4" />
    <EmptyGuide v-else-if="error && !data" icon="alert" title="加载失败" :desc="error" />

    <div v-if="data" class="metrics">
      <StatTile label="交易员数量" :value="data.traders.length" unit="位" icon="agentops" />
      <StatTile
        label="最佳累计收益"
        :value="fmtPct(Math.max(...stats.map((s) => s.profit_pct ?? -Infinity)))"
        :trend="Math.max(...stats.map((s) => s.profit_pct ?? 0)) >= 0 ? 'up' : 'down'"
      />
      <StatTile label="净值记录天数" :value="Math.max(...stats.map((s) => s.days), 0)" unit="天" />
      <StatTile label="基准" :value="data.benchmark.name || '沪深300'" />
    </div>

    <SectionCard v-show="!!data" title="净值曲线对比" desc="各交易员与沪深300 归一化对比（区间首值 = 100%）">
      <template #actions>
        <div class="seg">
          <button
            v-for="r in RANGES" :key="r.v" class="seg__btn"
            :class="{ 'is-on': range === r.v }" @click="range = r.v"
          >{{ r.l }}</button>
        </div>
        <button class="ui-btn" @click="load"><span>刷新</span></button>
      </template>
      <div ref="el" class="chart" />
    </SectionCard>

    <SectionCard v-if="data" title="交易员对比" desc="点击行进入详情" :padded="false">
      <div v-if="!stats.length" class="pad">
        <EmptyGuide icon="agentops" title="还没有交易员" desc="点右上角「新建交易员」添加。" />
      </div>
      <table v-else class="cmp">
        <thead>
          <tr>
            <th>交易员</th><th>模型</th><th class="ta-r">总资产</th><th class="ta-r">累计收益</th>
            <th class="ta-r">净值涨幅</th><th class="ta-r">持仓</th><th class="ta-r">成交</th>
            <th class="ta-r">净值天数</th><th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="s in stats" :key="s.id" :class="{ 'is-off': !s.enabled }" @click="emit('select', s.id)">
            <td><span class="dot" :style="{ background: s.color }" />{{ s.name }}</td>
            <td class="muted">{{ s.model }}</td>
            <td class="ta-r">{{ fmtMoney(s.total_assets) }}</td>
            <td class="ta-r" :class="(s.profit_pct ?? 0) >= 0 ? 'up' : 'down'">{{ fmtPct(s.profit_pct) }}</td>
            <td class="ta-r" :class="(s.nav_pct ?? 0) >= 0 ? 'up' : 'down'">{{ fmtPct(s.nav_pct) }}</td>
            <td class="ta-r">{{ s.positions ?? 0 }}</td>
            <td class="ta-r">{{ s.trades ?? 0 }}</td>
            <td class="ta-r">{{ s.days }}</td>
            <td class="ta-r"><span class="link">详情 →</span></td>
          </tr>
        </tbody>
      </table>
    </SectionCard>
  </div>
</template>

<style scoped>
.overview { display: flex; flex-direction: column; gap: var(--sp-4); }
/* .metrics 已收敛到全局样式（styles/base.css） */
.chart { width: 100%; height: 340px; }
.pad { padding: var(--sp-4); }
.seg { display: inline-flex; border: 1px solid var(--border); border-radius: var(--radius-sm); overflow: hidden; }
.seg__btn { background: none; border: none; padding: 4px 10px; font-size: var(--fs-xs); color: var(--text-sub); cursor: pointer; }
.seg__btn.is-on { background: var(--panel-2); color: var(--accent); font-weight: 600; }
.up { color: var(--up); }
.down { color: var(--down); }
.muted { color: var(--text-faint); font-size: var(--fs-xs); }
.cmp { width: 100%; border-collapse: collapse; font-size: var(--fs-sm); }
.cmp th { text-align: left; color: var(--text-faint); font-weight: 500; padding: 8px 14px; border-bottom: 1px solid var(--border); }
.cmp td { padding: 10px 14px; border-bottom: 1px solid var(--border); }
.cmp tbody tr { cursor: pointer; }
.cmp tbody tr:hover { background: var(--panel-2); }
.cmp tbody tr.is-off { opacity: 0.55; }
.ta-r { text-align: right; }
.dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 8px; }
.link { color: var(--accent); font-size: var(--fs-xs); }
</style>
