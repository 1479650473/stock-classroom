<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import SectionCard from '@/components/ui/SectionCard.vue'
import LoadingBlock from '@/components/ui/LoadingBlock.vue'
import EmptyGuide from '@/components/ui/EmptyGuide.vue'
import Icon from '@/components/Icon.vue'
import { usePersistedRef } from '@/composables/usePersistedRef'
import { getStrategyTrend, type StrategyTrendResult, type StrategyTrendItem } from '@/api'

/**
 * 策略决策追踪（跨多日 rank 变化）
 *
 * ## 为什么需要它
 * 选股页原来只能看**单日快照**。但策略的续持/卖出判断依赖**跨日变化**：
 *   · 卖出条件之一：**跌出 Top20%**（rank > 当日门槛）
 *   · 卖出条件之二：**FF 转好**
 * 只看一天，看不出"它正在逼近门槛"还是"刚掉出去"——也就看不出风险。
 *
 * ## 实际价值（本轮上线就发现了）
 * 持仓 002659 的 rank：**8 → 8 → 9 → 9 → 11**，距离门槛 20 还有 9 位，
 * 但**连续 4 天在往下滑** —— 这是"风险在积累"的早期信号，单日视图完全看不到。
 *
 * ## 诚实纪律
 * 只展示**真实存在的决策日期**，缺的日期列留空（`—`），**不插值不补齐**。
 */
const data = ref<StrategyTrendResult | null>(null)
const loading = ref(true)
const error = ref('')

/** 只显示 Top20% 内的（否则 100 行里大部分是噪音） */
const onlyTop = usePersistedRef<boolean>('strategy.trendOnlyTop', true)
const days = usePersistedRef<number>('strategy.trendDays', 5)

async function load() {
  loading.value = true
  error.value = ''
  try {
    data.value = await getStrategyTrend(days.value)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '决策追踪加载失败'
    data.value = null
  } finally {
    loading.value = false
  }
}
onMounted(load)

const dates = computed(() => data.value?.dates || [])
/** 表头日期显示成 MM-DD */
function shortDate(d: string): string {
  return `${d.slice(4, 6)}-${d.slice(6, 8)}`
}

const rows = computed<StrategyTrendItem[]>(() => {
  const items = data.value?.items || []
  return onlyTop.value ? items.filter((x) => x.in_top20) : items
})

/** 变化的方向语义：负数 = 排名上升（更靠前）—— 股票里"上升"是好事，所以用 up 色 */
function deltaTone(d: number | null): string {
  if (d == null) return 'flat'
  if (d < 0) return 'better'   // rank 变小 = 排名靠前 = 好
  if (d > 0) return 'worse'
  return 'flat'
}
function deltaText(d: number | null): string {
  if (d == null) return '—'
  if (d === 0) return '持平'
  return (d > 0 ? '↓' : '↑') + Math.abs(d)
}

/** rank 单元格配色：Top5 强 / Top20 正常 / 掉出门槛 警示 */
function cellClass(rank: number | null, threshold: number): string {
  if (rank == null) return 'cell cell--missing'
  if (rank > threshold) return 'cell cell--out'
  if (rank <= 5) return 'cell cell--hot'
  return 'cell'
}

const shownCount = computed(() => rows.value.length)
</script>

<template>
  <SectionCard
    :title="`决策追踪 · 最近 ${data?.dates.length || 0} 个决策日`"
    :desc="data?.note || '仅含真实存在的决策日期，缺的日期留空'"
  >
    <template #actions>
      <div class="tr__ctrl">
        <label class="tr__toggle">
          <input v-model="onlyTop" type="checkbox" />
          <span>只看 Top20%</span>
        </label>
        <select v-model.number="days" class="tr__sel" @change="load">
          <option :value="3">3 天</option>
          <option :value="5">5 天</option>
          <option :value="10">10 天</option>
          <option :value="20">20 天</option>
        </select>
        <button class="ui-btn ui-btn--sm" @click="load">
          <Icon name="refresh" :size="13" /> 刷新
        </button>
      </div>
    </template>

    <LoadingBlock v-if="loading && !data" :rows="5" />
    <EmptyGuide
      v-else-if="error || (data && !data.available)"
      icon="alert"
      title="读不到决策数据"
      :desc="error || data?.reason || '策略侧还没有产出多日 decision_*.csv'"
    >
      <template #action><button class="ui-btn" @click="load">重试</button></template>
    </EmptyGuide>

    <template v-else-if="data">
      <div class="tr__wrap">
        <table class="tr">
          <thead>
            <tr>
              <th class="tr__name">股票</th>
              <th v-for="d in dates" :key="d" class="tr__day">
                {{ shortDate(d) }}
              </th>
              <th class="tr__delta">变化</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in rows" :key="r.code">
              <td class="tr__name">
                <span class="mono tr__code">{{ r.code }}</span>
                <span class="tr__nm">{{ r.name || '—' }}</span>
              </td>
              <td
                v-for="d in dates"
                :key="d"
                :class="cellClass(r.ranks[d], r.threshold_latest || 20)"
              >
                {{ r.ranks[d] != null ? Math.round(r.ranks[d] as number) : '—' }}
              </td>
              <td class="tr__delta" :class="`delta delta--${deltaTone(r.delta)}`">
                {{ deltaText(r.delta) }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <p class="tr__foot">
        <Icon name="info" :size="12" />
        <span>
          数字是<b>当日 100 池内排名</b>（不是全市场）。排名<b>越小越靠前</b>；
          <b>超过当日 Top20% 门槛（{{ data.thresholds[dates[dates.length - 1]] ?? 20 }}）即触发策略卖出条件之一</b>。
          灰色格 = 当天已跌出门槛。缺的日期显示 <b>—</b>（该日无决策文件，未插值）。
          <template v-if="shownCount">当前显示 {{ shownCount }} 只。</template>
        </span>
      </p>
    </template>
  </SectionCard>
</template>

<style scoped>
.tr__ctrl { display: flex; align-items: center; gap: var(--sp-3); flex-wrap: wrap; }
.tr__toggle { display: inline-flex; align-items: center; gap: 5px; font-size: var(--fs-sm); color: var(--text-sub); cursor: pointer; }
.tr__sel {
  height: 26px; padding: 0 6px; font-size: var(--fs-sm);
  background: var(--bg-input, var(--bg-panel)); color: var(--text);
  border: 1px solid var(--border); border-radius: var(--radius-sm);
}

.tr__wrap { overflow-x: auto; }
.tr { width: 100%; border-collapse: collapse; font-size: var(--fs-sm); }
.tr th {
  padding: 7px 8px; font-weight: 500; color: var(--text-faint);
  font-size: var(--fs-xs); background: var(--bg-overlay);
  border-bottom: 1px solid var(--border-soft); white-space: nowrap;
}
.tr td { padding: 7px 8px; border-bottom: 1px solid var(--border-soft); text-align: center; }
.tr tbody tr:last-child td { border-bottom: 0; }

.tr__name { text-align: left !important; white-space: nowrap; }
.tr__code { color: var(--text-sub); font-size: var(--fs-xs); margin-right: 6px; }
.tr__nm { color: var(--text); }
.tr__day { min-width: 52px; }

/* rank 单元格 */
.cell { font-variant-numeric: tabular-nums; color: var(--text); }
.cell--hot { color: var(--gold); font-weight: 700; }
.cell--out { color: var(--text-faint); }
.cell--missing { color: var(--text-faint); opacity: .5; }

/* 变化：rank 变小 = 排名上升 = 好（用 up 色） */
.delta { font-variant-numeric: tabular-nums; font-weight: 600; white-space: nowrap; }
.delta--better { color: var(--up); }
.delta--worse { color: var(--down); }
.delta--flat { color: var(--text-faint); font-weight: 400; }

.tr__foot {
  display: flex; align-items: flex-start; gap: 6px;
  margin: var(--sp-4) 0 0; font-size: var(--fs-xs);
  color: var(--text-faint); line-height: 1.7;
}
.tr__foot > svg { flex: none; margin-top: 2px; }
</style>
