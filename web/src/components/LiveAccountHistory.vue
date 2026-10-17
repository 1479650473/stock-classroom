<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import SectionCard from '@/components/ui/SectionCard.vue'
import DataTable from '@/components/ui/DataTable.vue'
import type { DataColumn } from '@/components/ui/DataTable.vue'
import Icon from '@/components/Icon.vue'
import { useEChart, cssVar } from '@/composables/useEChart'
import { areaLineStyle, tooltipStyle } from '@/lib/chartTheme'
import type { LiveAccountHistory } from '@/api'

/**
 * 账户历史（走势 + 每日核对记录）
 *
 * ## 定位
 * 实盘页只做**账户信息反馈**（董事长 2026-10-17 定调）。
 * 本组件是"信息"的一部分：看账户这段时间怎么变的，而不是替你下单。
 *
 * ## 诚实纪律（重要）
 * 数据来自 `AUTO_LOG.md` 的**每日核对记录**，只有真的核对过才有记录。
 * 目前只有 4 天（10-13 ~ 10-16），**中间缺的日子绝不插值/补齐** ——
 * 那会画出一条"看起来连续"的假曲线。因此：
 *   · 图上每个点 = 一次真实核对
 *   · 标题直接写「共 N 天」，并在副标题说明未做插值
 *   · 每日一行标注该日读数是否通过恒等式校验（失败的会标红）
 */
const props = defineProps<{ history: LiveAccountHistory }>()

const items = computed(() => props.history.items || [])
const chartEl = ref<HTMLElement | null>(null)

const chartData = computed(() => ({
  dates: items.value.map((d) => d.date.slice(5)),
  total: items.value.map((d) => d.total_assets),
  mv: items.value.map((d) => d.market_value),
}))

const { draw } = useEChart(chartEl, () => {
  const { dates, total, mv } = chartData.value
  if (!dates.length) return {}
  return {
    grid: { left: 56, right: 16, top: 28, bottom: 26 },
    tooltip: { trigger: 'axis', ...tooltipStyle() },
    legend: { top: 0, right: 0, itemWidth: 10, itemHeight: 10, textStyle: { color: cssVar('--text-sub'), fontSize: 11 } },
    xAxis: {
      type: 'category', data: dates, boundaryGap: false,
      axisLabel: { color: cssVar('--text-faint') },
      axisLine: { lineStyle: { color: cssVar('--border') } },
    },
    yAxis: {
      type: 'value', scale: true,
      axisLabel: { color: cssVar('--text-faint') },
      splitLine: { lineStyle: { color: cssVar('--border-soft') } },
    },
    series: [
      // 注意：areaLineStyle 里已含 smooth/showSymbol，这里不要再写一遍
      // （写了 TS2783：会被后面的展开覆盖，虽然行为一样但类型检查不过）
      { name: '总资产', type: 'line', symbol: 'circle', symbolSize: 6,
        data: total, ...areaLineStyle(cssVar('--gold'), 2, 0.28) },
      { name: '持仓市值', type: 'line', symbol: 'circle', symbolSize: 5,
        data: mv, ...areaLineStyle(cssVar('--info', '#5B8FF9'), 2, 0.12) },
    ],
  }
})

watch(items, () => draw(), { flush: 'post' })

function money(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return '—'
  return v.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}
function signed(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return '—'
  return (v >= 0 ? '+' : '') + money(v)
}

/** 区间变化（首尾总资产差） */
const delta = computed<number | null>(() => {
  const a = items.value[0]?.total_assets
  const b = items.value[items.value.length - 1]?.total_assets
  if (a == null || b == null) return null
  return b - a
})

const columns: DataColumn[] = [
  { key: 'date', title: '日期', cellClass: 'mono' },
  { key: 'total_assets', title: '总资产', align: 'right', format: (r) => money(r.total_assets as number | null) },
  { key: 'market_value', title: '持仓市值', align: 'right', format: (r) => money(r.market_value as number | null) },
  { key: 'cash', title: '可用资金', align: 'right', format: (r) => money(r.cash as number | null) },
  { key: 'float_pnl', title: '持仓盈亏', align: 'right', format: (r) => signed(r.float_pnl as number | null) },
  { key: 'day_pnl', title: '当日盈亏', align: 'right', format: (r) => signed(r.day_pnl as number | null) },
  {
    key: 'checks_ok', title: '校验', align: 'center',
    format: (r) => (r.checks_ok === true ? '✓' : r.checks_ok === false ? '✗ 不自洽' : '—'),
  },
]
</script>

<template>
  <SectionCard
    :title="`账户走势 · 共 ${history.days} 天`"
    :desc="history.note || '来自策略侧每日核对记录，未做插值补齐'"
  >
    <template #actions>
      <span v-if="delta != null" class="hist__delta" :class="delta >= 0 ? 'up' : 'down'">
        <Icon name="trending" :size="13" />
        区间 {{ signed(delta) }}
      </span>
    </template>

    <div v-if="items.length" ref="chartEl" class="hist__chart" />

    <DataTable
      :columns="columns"
      :rows="items as unknown as Record<string, unknown>[]"
      compact
      row-key="date"
      storage-key="live.history"
      :page-size="20"
      empty-title="还没有历史核对记录"
      empty-desc="AUTO_LOG.md 里还没有带账户读数的日期章节。"
    />

    <p class="hist__foot">
      <Icon name="info" :size="12" />
      <span>
        每个点对应 <b>一次真实核对</b>（AUTO_LOG.md）——
        <b>缺的日子没有补</b>，所以曲线可能不连续。要让曲线更密，需要策略侧增加每日核对频率。
      </span>
    </p>
  </SectionCard>
</template>

<style scoped>
.hist__chart { height: 220px; margin-bottom: var(--sp-4); }
.hist__delta {
  display: inline-flex; align-items: center; gap: 4px;
  font-size: var(--fs-sm); font-variant-numeric: tabular-nums; font-weight: 600;
}
.hist__delta.up { color: var(--up); }
.hist__delta.down { color: var(--down); }
.hist__foot {
  display: flex; align-items: flex-start; gap: 6px;
  margin: var(--sp-4) 0 0; font-size: var(--fs-xs); color: var(--text-faint); line-height: 1.6;
}
.hist__foot > svg { flex: none; margin-top: 2px; }
</style>
