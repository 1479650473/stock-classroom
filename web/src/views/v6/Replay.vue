<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import SectionCard from '@/components/ui/SectionCard.vue'
import StatTile from '@/components/ui/StatTile.vue'
import EmptyGuide from '@/components/ui/EmptyGuide.vue'
import LoadingBlock from '@/components/ui/LoadingBlock.vue'
import Drawer from '@/components/ui/Drawer.vue'
import FormField from '@/components/ui/FormField.vue'
import Icon from '@/components/Icon.vue'
import KlineChart from '@/components/charts/KlineChart.vue'
import type { LwcBar, LwcMarker } from '@/components/charts/KlineChart.vue'
import { useEChart, cssVar } from '@/composables/useEChart'
import { useToastStore } from '@/stores/toast'
import { useJobsStore } from '@/stores/jobs'
import {
  getTraderReplays, getTraderProfiles, createTraderReplay, getTraderReplay,
  continueTraderReplay, distillTraderReplay, deleteTraderProfile, getKline,
} from '@/api'
import type { TraderProfile, TraderReplayDetail, TraderDecision } from '@/api'

echarts.use([LineChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

const toast = useToastStore()
const jobs = useJobsStore()

const runs = ref<TraderProfile[]>([])
const liveTraders = ref<TraderProfile[]>([])
const current = ref<TraderReplayDetail | null>(null)
const currentId = ref<number | null>(null)
const loading = ref(true)
const detailLoading = ref(false)
const drawerOpen = ref(false)
const creating = ref(false)
const expanded = ref<Record<string, boolean>>({})

const draft = ref({ source_profile_id: 0, start_date: '2024-01-02', days: 30 })

// K 线（按展开的交易日切片）
const klineBars = ref<Record<string, LwcBar[]>>({})
const klineLoading = ref<Record<string, boolean>>({})

const runningJob = computed(() => jobs.activeByKind('trader_replay'))
const isRunning = computed(() => !!runningJob.value)

async function loadRuns() {
  loading.value = true
  try {
    const [r, t] = await Promise.all([getTraderReplays(), getTraderProfiles()])
    runs.value = r.items || []
    liveTraders.value = t.items || []
    if (runs.value.length && !runs.value.some((x) => x.id === currentId.value)) {
      currentId.value = runs.value[0].id
    }
    if (!runs.value.length) currentId.value = null
  } catch (e) {
    toast.error('加载失败：' + (e instanceof Error ? e.message : String(e)))
  } finally {
    loading.value = false
  }
}

async function loadDetail() {
  if (!currentId.value) { current.value = null; return }
  detailLoading.value = true
  try {
    current.value = await getTraderReplay(currentId.value, 120)
    klineBars.value = {}
  } catch (e) {
    toast.error('回放详情加载失败：' + (e instanceof Error ? e.message : String(e)))
  } finally {
    detailLoading.value = false
  }
}

onMounted(async () => { await loadRuns(); await loadDetail() })
watch(currentId, loadDetail)
watch(
  () => jobs.byKind('trader_replay').map((j) => `${j.id}:${j.doneTick || 0}:${j.status}`).join('|'),
  (v, o) => { if (v !== o) { loadRuns().then(loadDetail) } },
)

function openCreate() {
  draft.value = {
    source_profile_id: liveTraders.value[0]?.id || 0,
    start_date: '2024-01-02', days: 30,
  }
  drawerOpen.value = true
}

async function create() {
  if (!draft.value.source_profile_id) { toast.error('请选择按哪个交易员回放'); return }
  creating.value = true
  try {
    const r = await createTraderReplay({
      source_profile_id: draft.value.source_profile_id,
      start_date: draft.value.start_date,
      days: Number(draft.value.days) || 30,
    })
    toast.success('回放已创建，正在逐日运行…')
    drawerOpen.value = false
    await loadRuns()
    currentId.value = r.profile.id
    jobs.attach(r.job.job_id)
  } catch (e) {
    toast.error('创建失败：' + (e instanceof Error ? e.message : String(e)))
  } finally {
    creating.value = false
  }
}

async function cont() {
  if (!currentId.value) return
  try {
    const r = await continueTraderReplay(currentId.value, 30)
    jobs.attach(r.job.job_id)
    toast.success('继续回放中…')
  } catch (e) {
    toast.error('续跑失败：' + (e instanceof Error ? e.message : String(e)))
  }
}

async function distill() {
  const run = current.value?.profile
  if (!run) return
  const src = (run.meta?.source_profile_id) || 0
  if (!src) { toast.error('找不到源交易员'); return }
  try {
    const r = await distillTraderReplay(run.id, src)
    toast.success(`已把 ${r.copied} 条回放经验写入「${r.target}」`)
  } catch (e) {
    toast.error('经验回流失败：' + (e instanceof Error ? e.message : String(e)))
  }
}

async function removeRun(p: TraderProfile) {
  if (!window.confirm(`删除回放「${p.name}」？其账户与全部逐日记录将一并删除。`)) return
  try {
    await deleteTraderProfile(p.id)
    toast.success('已删除')
    await loadRuns()
  } catch (e) {
    toast.error('删除失败：' + (e instanceof Error ? e.message : String(e)))
  }
}

// ── 展示辅助 ──
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
function actionSummary(d: TraderDecision) {
  const n = d.plan?.length || 0
  if (!n) return '保持现状'
  return d.plan.map((o) => `${o.side === 'buy' ? '买' : '卖'} ${o.name || o.code} ${o.qty}`).join(' · ')
}
function dayNav(d: TraderDecision) { return d.nav_after }
function toggle(key: string) { expanded.value[key] = !expanded.value[key] }

watch(expanded, () => {
  for (const d of current.value?.decisions || []) {
    if (expanded.value['d' + d.id]) {
      for (const c of dayCodes(d)) loadKline(c, d.trade_date)
    }
  }
}, { deep: true })

function dayCodes(d: TraderDecision): string[] {
  const codes = new Set<string>()
  for (const o of d.plan || []) codes.add(o.code)
  const pos = ((d.context as Record<string, unknown>)?.positions as { code: string }[]) || []
  for (const p of pos) codes.add(p.code)
  return [...codes].slice(0, 3)
}

async function loadKline(code: string, asOf: string) {
  const key = `${code}@${asOf}`
  if (klineBars.value[key] || klineLoading.value[key]) return
  klineLoading.value[key] = true
  try {
    const all = await getKline(code, 1600)
    const bars = (all as unknown as { date: string; open: number; high: number; low: number; close: number; volume: number }[])
      .map((b) => ({
        time: b.date.length === 8 ? `${b.date.slice(0, 4)}-${b.date.slice(4, 6)}-${b.date.slice(6, 8)}` : b.date,
        open: b.open, high: b.high, low: b.low, close: b.close, volume: b.volume,
      }))
      .filter((b) => b.time <= asOf)
    klineBars.value[key] = bars as LwcBar[]
  } catch {
    klineBars.value[key] = []
  } finally {
    klineLoading.value[key] = false
  }
}
function markersFor(d: TraderDecision): LwcMarker[] {
  return (d.plan || []).map((o) => ({
    time: d.trade_date, position: o.side === 'buy' ? 'belowBar' : 'aboveBar',
    color: o.side === 'buy' ? '#e5484d' : '#3fb950', shape: o.side === 'buy' ? 'arrowUp' : 'arrowDown',
    text: `${o.side === 'buy' ? '买' : '卖'}${o.qty}`,
  })) as LwcMarker[]
}

// ── 净值曲线（回放 vs 沪深300）──
const chartEl = ref<HTMLElement | null>(null)
const navSeries = computed(() => {
  const d = current.value
  if (!d) return [] as any[]
  return [{ name: '回放净值', type: 'line', showSymbol: false, smooth: true, lineStyle: { width: 2 },
            itemStyle: { color: cssVar('--accent', '#D4A574') },
            data: d.nav.map((p) => [p.date, p.nav]) }] as any[]
})
const chart = useEChart(chartEl, () => ({
  animation: false,
  grid: { left: 52, right: 16, top: 30, bottom: 36 },
  tooltip: { trigger: 'axis' },
  legend: { top: 2, textStyle: { color: cssVar('--text-sub', '#9AA4B2'), fontSize: 11 } },
  xAxis: { type: 'time', axisLabel: { color: cssVar('--text-faint', '#6B7280'), fontSize: 10, hideOverlap: true },
           axisLine: { lineStyle: { color: cssVar('--border', '#2A2E37') } } },
  yAxis: { type: 'value', scale: true,
           axisLabel: { color: cssVar('--text-faint', '#6B7280'), fontSize: 10, formatter: (v: number) => (v * 100).toFixed(0) + '%' },
           splitLine: { lineStyle: { color: cssVar('--border', '#2A2E37') } } },
  series: navSeries.value,
}))
watch([current, navSeries], async () => { await Promise.resolve(); chart.draw() })
</script>

<template>
  <div class="replay">
    <div class="bar">
      <div class="bar__left">
        <select v-model="currentId" class="ui-select">
          <option :value="null" disabled>选择回放</option>
          <option v-for="r in runs" :key="r.id" :value="r.id">
            {{ r.name }}（{{ r.meta?.done_days || 0 }}天）
          </option>
        </select>
        <span v-if="isRunning" class="running">回放中… {{ runningJob?.msg }}</span>
      </div>
      <button class="ui-btn ui-btn--primary" @click="openCreate"><Icon name="plus" :size="14" /><span>新建回放</span></button>
    </div>

    <LoadingBlock v-if="loading && !runs.length" :rows="4" />
    <EmptyGuide v-else-if="!runs.length" icon="backtest" title="还没有回放"
      desc="选一个交易员和一个历史起点，让它在过去的数据里逐日做模拟（无前视）。" >
      <template #action><button class="ui-btn ui-btn--primary" @click="openCreate">新建回放</button></template>
    </EmptyGuide>

    <template v-else-if="current">
      <!-- 头部 -->
      <div class="metrics">
        <StatTile label="回放天数" :value="current.profile.meta?.done_days || 0" unit="天" />
        <StatTile label="账户总资产" :value="fmtMoney(current.summary.total_assets)" icon="wallet" />
        <StatTile label="累计盈亏" :value="fmtMoney(current.summary.total_profit)"
          :trend="(current.summary.total_profit ?? 0) >= 0 ? 'up' : 'down'"
          :hint="fmtPct(current.summary.total_profit_pct)"
          :hint-trend="(current.summary.total_profit ?? 0) >= 0 ? 'up' : 'down'" />
        <StatTile label="持仓" :value="current.summary.positions ?? 0" unit="只" />
        <StatTile label="当前游标" :value="current.profile.meta?.cursor || '—'" />
      </div>

      <div class="actions">
        <span class="src">按「{{ current.profile.meta?.source_name }}」回放 · 起始 {{ current.profile.meta?.start_date }}</span>
        <button class="ui-btn" :disabled="isRunning" @click="cont"><Icon name="play" :size="13" /><span>继续 30 天</span></button>
        <button class="ui-btn" @click="distill"><Icon name="save" :size="13" /><span>经验回流到源交易员</span></button>
        <button class="ui-btn ui-btn--ghost" @click="removeRun(current.profile)"><Icon name="trash" :size="13" /><span>删除</span></button>
      </div>

      <SectionCard title="回放净值" desc="无前视逐日模拟的账户净值（1.0 = 起始）">
        <div ref="chartEl" class="chart" />
      </SectionCard>

      <SectionCard title="逐日回放" :desc="`共 ${current.decisions.length} 个交易日 · 点击展开当日过程`" :padded="false">
        <div class="days">
          <div v-for="d in current.decisions" :key="d.id" class="day">
            <div class="day__head" @click="toggle('d' + d.id)">
              <span class="day__date">{{ d.trade_date }}</span>
              <span class="tag" :class="d.plan?.length ? 'tag--act' : 'tag--hold'">{{ actionSummary(d) }}</span>
              <span class="day__nav" :class="(dayNav(d) ?? 1) >= 1 ? 'up' : 'down'">
                {{ dayNav(d) != null ? fmtPct((dayNav(d)! - 1) * 100) : '—' }}
              </span>
              <span class="day__status" :class="d.status">{{ d.status === 'done' ? '已完成' : d.status === 'error' ? '失败' : d.status }}</span>
              <Icon class="day__chev" :name="expanded['d' + d.id] ? 'chevron-down' : 'chevron-right'" :size="14" />
            </div>

            <div v-if="expanded['d' + d.id]" class="day__body">
              <div class="grid2">
                <div class="block">
                  <div class="block__title">思考过程</div>
                  <p class="prose">{{ d.thinking || '—' }}</p>
                  <p v-if="d.reflection" class="prose prose--sub">复盘：{{ d.reflection }}</p>
                </div>
                <div class="block">
                  <div class="block__title">当日委托与账户</div>
                  <table class="mini">
                    <thead><tr><th>股票</th><th>方向</th><th class="ta-r">数量</th><th class="ta-r">价格</th><th>结果</th></tr></thead>
                    <tbody>
                      <tr v-for="(o, i) in d.plan" :key="i">
                        <td>{{ o.name || o.code }}</td>
                        <td :class="o.side === 'buy' ? 'up' : 'down'">{{ o.side === 'buy' ? '买入' : '卖出' }}</td>
                        <td class="ta-r">{{ o.qty }}</td>
                        <td class="ta-r">{{ (d.executions || [])[i]?.price || o.price || '市价' }}</td>
                        <td><span :class="(d.executions || [])[i]?.ok ? 'ok' : 'bad'">{{ (d.executions || [])[i]?.detail || '未执行' }}</span></td>
                      </tr>
                      <tr v-if="!d.plan?.length"><td colspan="5" class="muted">当日无操作</td></tr>
                    </tbody>
                  </table>
                  <div class="acct">
                    <span>总资产 {{ fmtMoney(d.total_assets_after) }}</span>
                    <span>持仓 {{ (((d.context as Record<string, unknown>)?.positions as unknown[]) || []).length }} 只</span>
                  </div>
                </div>
              </div>

              <div v-if="dayCodes(d).length" class="kline">
                <div class="block__title">当日相关个股走势（截至 {{ d.trade_date }}）</div>
                <div v-for="c in dayCodes(d)" :key="c" class="kline__item">
                  <div class="kline__code">{{ c }}</div>
                  <div v-if="klineLoading[c + '@' + d.trade_date]" class="muted">加载中…</div>
                  <KlineChart
                    v-else-if="klineBars[c + '@' + d.trade_date]?.length"
                    :bars="klineBars[c + '@' + d.trade_date]"
                    :markers="markersFor(d)"
                    :height="260" :mas="[5, 20]"
                    :key="c + '@' + d.trade_date"
                  />
                  <div v-else class="muted" @click="loadKline(c, d.trade_date)">点击加载 K 线</div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </SectionCard>
    </template>

    <!-- 新建回放 -->
    <Drawer :open="drawerOpen" title="新建回放" desc="让某个交易员在过去的数据里逐日模拟（无前视）" :width="440" @update:open="drawerOpen = $event">
      <div class="form">
        <FormField label="按哪个交易员回放" hint="沿用它的模型、本金与交易规则">
          <select v-model="draft.source_profile_id" class="ui-select">
            <option v-for="t in liveTraders" :key="t.id" :value="t.id">{{ t.name }}（{{ t.model || '默认模型' }}）</option>
          </select>
        </FormField>
        <FormField label="起始日期" hint="从该日起的交易日开始（历史新闻不可回溯）">
          <input v-model="draft.start_date" class="ui-input" type="date" />
        </FormField>
        <FormField label="本次天数" hint="单次最多 30 个交易日，可后续继续">
          <input v-model.number="draft.days" class="ui-input" type="number" min="1" max="30" />
        </FormField>
        <div class="note">
          回放从空记忆开始，逐日给模型「截至当日」的行情/候选/持仓，按当日价成交并结算。
          模型训练数据可能记得那段历史，这是 LLM 回测无法完全消除的局限。
        </div>
        <div class="form__foot">
          <button class="ui-btn" @click="drawerOpen = false">取消</button>
          <button class="ui-btn ui-btn--primary" :disabled="creating" @click="create">{{ creating ? '创建中…' : '开始回放' }}</button>
        </div>
      </div>
    </Drawer>
  </div>
</template>

<style scoped>
.replay { display: flex; flex-direction: column; gap: var(--sp-4); }
.bar { display: flex; align-items: center; justify-content: space-between; gap: var(--sp-3); }
.bar__left { display: flex; align-items: center; gap: var(--sp-3); }
.running { font-size: var(--fs-xs); color: var(--accent); }
.metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: var(--sp-3); }
.actions { display: flex; align-items: center; gap: var(--sp-2); flex-wrap: wrap; }
.src { font-size: var(--fs-sm); color: var(--text-sub); margin-right: auto; }
.chart { width: 100%; height: 300px; }
.days { display: flex; flex-direction: column; }
.day { border-bottom: 1px solid var(--border); }
.day:last-child { border-bottom: none; }
.day__head { display: flex; align-items: center; gap: var(--sp-3); padding: var(--sp-3) var(--sp-4); cursor: pointer; }
.day__head:hover { background: var(--panel-2); }
.day__date { font-variant-numeric: tabular-nums; font-size: var(--fs-sm); color: var(--text-sub); width: 92px; flex: none; }
.day__nav { font-size: var(--fs-xs); font-weight: 600; }
.day__status { font-size: var(--fs-xs); color: var(--text-faint); margin-left: auto; }
.day__status.error { color: var(--up); }
.day__chev { color: var(--text-faint); flex: none; }
.day__body { padding: 0 var(--sp-4) var(--sp-4); display: flex; flex-direction: column; gap: var(--sp-4); }
.grid2 { display: grid; grid-template-columns: 1.4fr 1fr; gap: var(--sp-4); }
@media (max-width: 1000px) { .grid2 { grid-template-columns: 1fr; } }
.block { display: flex; flex-direction: column; gap: 8px; }
.block__title { font-size: var(--fs-sm); font-weight: 600; color: var(--text-sub); }
.prose { font-size: var(--fs-sm); line-height: 1.7; color: var(--text); white-space: pre-wrap; margin: 0; }
.prose--sub { color: var(--text-sub); }
.mini { width: 100%; border-collapse: collapse; font-size: var(--fs-sm); }
.mini th { text-align: left; color: var(--text-faint); font-weight: 500; padding: 5px 8px; border-bottom: 1px solid var(--border); }
.mini td { padding: 6px 8px; border-bottom: 1px solid var(--border); }
.ta-r { text-align: right; }
.up { color: var(--up); }
.down { color: var(--down); }
.ok { color: var(--ok); }
.bad { color: var(--up); }
.muted { color: var(--text-faint); font-size: var(--fs-xs); }
.acct { display: flex; gap: var(--sp-4); font-size: var(--fs-xs); color: var(--text-sub); }
.tag { font-size: var(--fs-xs); padding: 2px 8px; border-radius: 999px; font-weight: 600; }
.tag--act { background: color-mix(in srgb, var(--accent) 16%, transparent); color: var(--accent); }
.tag--hold { background: var(--panel-2); color: var(--text-sub); }
.kline { display: flex; flex-direction: column; gap: var(--sp-2); }
.kline__item { border: 1px solid var(--border); border-radius: var(--radius-sm); overflow: hidden; }
.kline__code { font-size: var(--fs-xs); color: var(--accent); padding: 6px 10px; }
.form { display: flex; flex-direction: column; gap: var(--sp-4); }
.form__foot { display: flex; justify-content: flex-end; gap: var(--sp-2); }
.note { font-size: var(--fs-xs); color: var(--text-faint); line-height: 1.7; padding: var(--sp-3); background: var(--panel-2); border-radius: var(--radius-sm); }
</style>
