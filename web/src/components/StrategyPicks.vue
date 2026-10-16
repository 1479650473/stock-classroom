<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import SectionCard from '@/components/ui/SectionCard.vue'
import StatTile from '@/components/ui/StatTile.vue'
import DataTable from '@/components/ui/DataTable.vue'
import type { DataColumn } from '@/components/ui/DataTable.vue'
import SegmentedControl from '@/components/ui/SegmentedControl.vue'
import LoadingBlock from '@/components/ui/LoadingBlock.vue'
import EmptyGuide from '@/components/ui/EmptyGuide.vue'
import Icon from '@/components/Icon.vue'
import { getStrategyPicks, getStrategyDates, type StrategyPicksResult, type StrategyPick } from '@/api'
import { usePersistedRef } from '@/composables/usePersistedRef'

/**
 * 实盘策略选股（pali）—— 软件服务于策略的入口。
 *
 * ## 它和「全市场扫描」的区别（这是本页存在的理由）
 * - **本页**：展示**实盘策略（pali）真正的决策结果** ——
 *   决策 CSV 的 `pred / ff20 / rank` + 排雷 JSON 的 `PASS/CAUTION/REJECT`。
 *   **只读、不加工**，所见即策略所见。
 * - 「全市场扫描」：软件自带的 `compute_factor_picks` 多因子扫描，**与实盘无关**。
 *   保留它是有用的对照，但**默认视图必须是实盘策略**。
 *
 * ## 三条如实展示的纪律
 * 1. `pred / ff20 / rank` 原样显示，不做任何换算或归一。
 * 2. 排雷状态分四种，**不能混**：
 *    - `PASS/CAUTION/REJECT` —— 策略真的查过了
 *    - `NOT_CHECKED` —— 排雷只跑 TopN（默认 15），**程序根本没跑它**（正常）
 *    - `UNKNOWN` —— 在深度之内却没有记录（**该查却没查**，异常）
 * 3. 是否可买由**策略硬约束**判定（只主板 + 只买 PASS），并**显示被什么挡住** ——
 *    否则用户会看到"策略 Rank1 看好却买不了"而不知原因（如 688521 是科创板）。
 */
const date = ref<string>('')
const data = ref<StrategyPicksResult | null>(null)
const dates = ref<string[]>([])
const loading = ref(true)
const error = ref('')
/** 只显示可买 / 全部候选 */
const onlyBuyable = usePersistedRef<boolean>('strategy.onlyBuyable', false)

async function load(d?: string) {
  loading.value = true
  error.value = ''
  try {
    data.value = await getStrategyPicks(d || undefined)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '策略决策加载失败'
    data.value = null
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  try { dates.value = (await getStrategyDates()).dates } catch { /* 无历史日期则忽略 */ }
  await load()
})

const items = computed<StrategyPick[]>(() => data.value?.items || [])
const shown = computed(() => (onlyBuyable.value ? items.value.filter((x) => x.buyable) : items.value))

const riskStats = computed(() => {
  const c: Record<string, number> = { PASS: 0, CAUTION: 0, REJECT: 0, UNKNOWN: 0, NOT_CHECKED: 0 }
  for (const it of items.value) c[it.risk_level] = (c[it.risk_level] || 0) + 1
  return c
})

/** 排雷状态 → 展示色。NOT_CHECKED 用中性（正常），UNKNOWN 用警示（异常） */
function riskTone(lv: string): string {
  if (lv === 'PASS') return 'ok'
  if (lv === 'CAUTION') return 'warn'
  if (lv === 'REJECT') return 'bad'
  if (lv === 'UNKNOWN') return 'warn'
  return 'muted'
}

const columns: DataColumn[] = [
  { key: 'rank', title: '排名', align: 'right', width: '68px', format: (r) => (r.rank == null ? '—' : String(Math.round(Number(r.rank)))) },
  { key: 'code', title: '代码', cellClass: 'mono' },
  { key: 'name', title: '名称' },
  { key: 'board_cn', title: '板块', width: '76px' },
  { key: 'pred', title: '模型打分', align: 'right', sortable: true, format: (r) => (r.pred == null ? '—' : Number(r.pred).toFixed(5)) },
  { key: 'ff20', title: '资金流(20日)', align: 'right', sortable: true, format: (r) => fmtMoney(r.ff20 as number | null) },
  { key: 'ff_ok', title: 'FF', align: 'center', format: (r) => (r.ff_ok ? '✓' : '✗') },
  { key: 'risk_level_cn', title: '排雷' },
  { key: 'blocked_by', title: '可否买入', format: (r) => ((r.buyable as boolean) ? '✓ 可买' : (r.blocked_by as string[]).join(' / ') || '—') },
]

function fmtMoney(v: number | null): string {
  if (v == null || Number.isNaN(v)) return '—'
  const a = Math.abs(v)
  if (a >= 1e8) return (v / 1e8).toFixed(2) + ' 亿'
  if (a >= 1e4) return (v / 1e4).toFixed(0) + ' 万'
  return v.toFixed(0)
}

const dateOptions = computed(() =>
  (dates.value.length ? dates.value : (data.value?.date ? [data.value.date] : []))
    .map((d) => ({ value: d, label: `${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6, 8)}` })),
)

/* ── 持仓显示 ──
 * 持仓来自策略侧的 AUTO_LOG.md（实测解析：「持仓：002659 凯文教育 700 股 | 成本 …」）。
 * 关键：**读不到就说读不到**，绝不显示成"空仓" —— 那会把"我解析失败"伪装成
 * "策略没持仓"，是典型的误导性降级（这条纪律本项目反复强调过）。
 */
type Pos = Record<string, unknown>

const pos = computed<Pos | null>(() => {
  const p = data.value?.position as Pos | null | undefined
  return p && (p.code || p.qty === 0) ? p : null
})
/** 读不到持仓（而非"确实空仓"）—— 两者必须区分 */
const posUnknown = computed(() => !!data.value?.available && !data.value?.position)

const posLabel = computed(() => {
  if (posUnknown.value) return '读取失败'
  if (!pos.value) return '—'
  if (!pos.value.code) return '空仓'
  return String(pos.value.name || pos.value.code)
})

const posHint = computed(() => {
  if (posUnknown.value) return 'AUTO_LOG.md 里没解析到持仓行'
  if (!pos.value) return '—'
  if (!pos.value.code) return '策略当前无持仓'
  const r = pos.value.rank
  const inTop = pos.value.in_top20
  const parts = [`${pos.value.qty} 股`]
  if (typeof r === 'number') parts.push(`池内 rank ${Math.round(r)}`)
  parts.push(inTop ? '在 Top20% 内' : '已跌出 Top20%')
  return parts.join(' · ')
})

const posTrend = computed<'up' | 'down' | 'neutral'>(() => {
  if (posUnknown.value || !pos.value?.code) return 'neutral'
  return pos.value.in_top20 ? 'up' : 'down'
})

function pickDate(v: string) {
  date.value = v
  void load(v)
}
</script>

<template>
  <div class="sp">
    <SectionCard>
      <div class="sp__head">
        <div class="sp__title">
          <Icon name="picks" :size="15" />
          <b>实盘策略决策（pali）</b>
          <span v-if="data?.date" class="sp__date mono">
            {{ data.date.slice(0, 4) }}-{{ data.date.slice(4, 6) }}-{{ data.date.slice(6, 8) }}
          </span>
        </div>
        <div class="sp__ctrl">
          <SegmentedControl
            v-if="dateOptions.length > 1"
            :model-value="date || dateOptions[0]?.value || ''"
            :options="dateOptions"
            size="sm"
            @update:model-value="pickDate"
          />
          <label class="sp__toggle">
            <input v-model="onlyBuyable" type="checkbox" />
            <span>只看可买</span>
          </label>
          <button class="ui-btn ui-btn--sm" @click="load(date || undefined)">
            <Icon name="refresh" :size="13" /> 刷新
          </button>
        </div>
      </div>

      <p class="sp__hint">
        这是<b>实盘策略真正用的决策</b>（<span class="mono">{{ data?.source || '—' }}</span>），
        原样展示、软件侧不做任何加工。<b>与「全市场扫描」是两套东西</b> —— 后者是软件自带的对照扫描，与实盘无关。
      </p>
    </SectionCard>

    <LoadingBlock v-if="loading && !data" :rows="5" />

    <EmptyGuide
      v-else-if="error || (data && !data.available)"
      icon="alert"
      title="读不到策略决策"
      :desc="error || data?.reason || '策略侧还没有产出 decision_*.csv'"
    >
      <template #action>
        <button class="ui-btn" @click="load(date || undefined)">重试</button>
      </template>
    </EmptyGuide>

    <template v-else-if="data">
      <!-- 概览：先回答"现在能不能买、买了什么" -->
      <div class="sp__tiles">
        <StatTile label="候选（100 池）" :value="items.length" unit="只" hint="策略打分排序" />
        <StatTile
          label="可买入"
          :value="data.buyable_count ?? 0"
          unit="只"
          :hint="`只主板 + 只买 PASS`"
          :trend="(data.buyable_count ?? 0) > 0 ? 'up' : 'neutral'"
        />
        <StatTile
          label="排雷覆盖"
          :value="data.risk.checked ?? 0"
          unit="条"
          :hint="`深度 Top${data.risk.depth ?? '—'} · ${data.risk.ts || '—'}`"
        />
        <StatTile
          label="策略持仓"
          :value="posLabel"
          :hint="posHint"
          :trend="posTrend"
        />
      </div>

      <!-- 排雷状态分布：一眼看清"哪些查过、哪些没查" -->
      <SectionCard title="排雷状态分布" desc="NOT_CHECKED = 排雷只跑 TopN，程序没跑它（正常）；UNKNOWN = 该查却没记录（异常）">
        <div class="sp__risk">
          <span class="sp__risk-item tone-ok">PASS {{ riskStats.PASS }}</span>
          <span class="sp__risk-item tone-warn">CAUTION {{ riskStats.CAUTION }}</span>
          <span class="sp__risk-item tone-bad">REJECT {{ riskStats.REJECT }}</span>
          <span class="sp__risk-item tone-warn">UNKNOWN {{ riskStats.UNKNOWN }}</span>
          <span class="sp__risk-item tone-muted">NOT_CHECKED {{ riskStats.NOT_CHECKED }}</span>
        </div>
      </SectionCard>

      <SectionCard :title="`策略候选（${shown.length} 只）`" :desc="onlyBuyable ? '仅显示满足硬约束（主板 + PASS）的标的' : '按策略 rank 排序，排名即策略的优先级'">
        <DataTable
          :columns="columns"
          :rows="shown as unknown as Record<string, unknown>[]"
          compact
          row-key="code"
          storage-key="strategy.picks"
          :page-size="25"
          empty-title="没有候选"
          empty-desc="换一个交易日，或取消「只看可买」。"
        />
      </SectionCard>

      <!-- 策略执行摘要：回答"策略今天到底做了什么决定" -->
      <SectionCard v-if="data.summary?.available" :title="`策略执行摘要 · ${data.summary.date}`" desc="摘自策略侧 AUTO_LOG.md（原样，未改写）">
        <ul class="sp__log">
          <li v-for="(l, i) in data.summary.lines" :key="i">{{ String(l).replace(/^-\s*/, '') }}</li>
        </ul>
      </SectionCard>
    </template>
  </div>
</template>

<style scoped>
.sp { display: flex; flex-direction: column; gap: var(--section-gap); }
.sp__head { display: flex; align-items: center; justify-content: space-between; gap: var(--sp-4); flex-wrap: wrap; }
.sp__title { display: flex; align-items: center; gap: 7px; font-size: var(--fs-lg); color: var(--text); }
.sp__date { font-size: var(--fs-sm); color: var(--text-sub); }
.sp__ctrl { display: flex; align-items: center; gap: var(--sp-3); flex-wrap: wrap; }
.sp__toggle { display: inline-flex; align-items: center; gap: 6px; font-size: var(--fs-sm); color: var(--text-sub); cursor: pointer; }
.sp__hint { margin: var(--sp-3) 0 0; font-size: var(--fs-sm); color: var(--text-sub); line-height: 1.6; }

.sp__tiles { display: grid; gap: var(--sp-3); grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); }

.sp__risk { display: flex; gap: var(--sp-3); flex-wrap: wrap; }
.sp__risk-item {
  padding: 4px 12px; border-radius: var(--radius-pill);
  border: 1px solid var(--border); font-size: var(--fs-sm);
  font-variant-numeric: tabular-nums;
}
.tone-ok { color: var(--ok); border-color: color-mix(in srgb, var(--ok) 45%, var(--border)); }
.tone-warn { color: var(--warn); border-color: color-mix(in srgb, var(--warn) 45%, var(--border)); }
.tone-bad { color: var(--up); border-color: color-mix(in srgb, var(--up) 45%, var(--border)); }
.tone-muted { color: var(--text-faint); }

.sp__log { margin: 0; padding-left: 1.1em; font-size: var(--fs-sm); line-height: 1.85; color: var(--text-sub); }
.sp__log li { margin-bottom: 2px; }
</style>
