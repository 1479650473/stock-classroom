<script setup lang="ts">
/**
 * 因子挖掘（AlphaGPT 式）：公式搜索 + 回测奖励
 *  - 挖一次：遗传搜索 → 样本外检验 → 相关性去重 → 多因子合成
 *  - 滚动验证：多折「训练独立搜索 → 紧接测试段评估」，判断是否跨期稳定
 * 进度复用全局任务中心（jobs store），完成后自动刷新结果。
 */
import { computed, onMounted, ref, watch } from 'vue'
import SectionCard from '@/components/ui/SectionCard.vue'
import FormField from '@/components/ui/FormField.vue'
import DataTable from '@/components/ui/DataTable.vue'
import LoadingBlock from '@/components/ui/LoadingBlock.vue'
import EmptyGuide from '@/components/ui/EmptyGuide.vue'
import Icon from '@/components/Icon.vue'
import { useJobsStore } from '@/stores/jobs'
import { useToastStore } from '@/stores/toast'
import {
  getAlphaCompositeReport, getAlphaMeta, getAlphaRun, getAlphaRuns, getAlphaSmb, getAlphaZoo,
  startAlphaMine, startAlphaWalkforward,
} from '@/api'
import type { AlphaCompositeReport, AlphaFormula, AlphaRun, AlphaSmbResult, AlphaZooRow } from '@/api'

const jobs = useJobsStore()
const toast = useToastStore()

const loading = ref(true)
const starting = ref(false)
const runs = ref<AlphaRun[]>([])
const current = ref<AlphaRun | null>(null)
const openForm = ref(false)
const meta = ref<{ defaults: Record<string, number | string>; features: string[]; operators: string[] } | null>(null)
// 因子体检榜 + 组合验证（借鉴 Qbot 的因子体系，服务我们自己的体检台）
const tab = ref<'mine' | 'zoo' | 'composite' | 'smb'>('mine')
const smb = ref<AlphaSmbResult | null>(null)
const zooSort = ref('ic')
const zoo = ref<AlphaZooRow[]>([])
const zooMeta = ref<Record<string, unknown>>({})
const comp = ref<AlphaCompositeReport | null>(null)

const form = ref({
  codes: 300, start: '2021-07-01', end: '2025-12-31',
  pop: 120, gens: 18, hold: 5, topk: 20, top: 8,
  folds: 5, train_months: 24, test_months: 6,
})

const activeJob = computed(() => jobs.activeByKind('alpha'))
const running = computed(() => !!activeJob.value)
const progress = computed(() => activeJob.value?.pct ?? 0)
const progressMsg = computed(() => activeJob.value?.msg || '准备中…')

const metaOf = (r: AlphaRun) => (r.meta || {}) as Record<string, number | string>
const fmt = (v: unknown, digits = 2) => {
  const n = Number(v)
  if (!Number.isFinite(n)) return '—'
  return (n >= 0 ? '+' : '') + (n * 100).toFixed(digits) + '%'
}
const num = (v: unknown, digits = 2) => {
  const n = Number(v)
  return Number.isFinite(n) ? n.toFixed(digits) : '—'
}

async function load(limit = 20) {
  loading.value = true
  try {
    const r = await getAlphaRuns(limit)
    runs.value = r.items || []
    const first = runs.value.find((x) => x.kind === 'mine') || runs.value[0]
    if (first && (!current.value || current.value.id !== first.id)) await select(first.id)
  } catch (e) {
    toast.error(e instanceof Error ? e.message : String(e))
  } finally {
    loading.value = false
  }
}

async function select(id: number) {
  try {
    current.value = await getAlphaRun(id)
  } catch (e) {
    toast.error(e instanceof Error ? e.message : String(e))
  }
}

async function loadMeta() {
  try {
    meta.value = await getAlphaMeta()
  } catch { /* 忽略：元信息只用于展示特征/算子数量 */ }
}

async function start(kind: 'mine' | 'walkforward') {
  starting.value = true
  try {
    const params = kind === 'mine'
      ? { codes: form.value.codes, start: form.value.start, end: form.value.end, pop: form.value.pop, gens: form.value.gens, hold: form.value.hold, topk: form.value.topk, top: form.value.top }
      : { codes: form.value.codes, start: form.value.start, end: form.value.end, pop: form.value.pop, gens: form.value.gens, hold: form.value.hold, topk: form.value.topk, folds: form.value.folds, train_months: form.value.train_months, test_months: form.value.test_months, combo: 5 }
    const id = await jobs.run({
      kind: 'alpha',
      title: kind === 'mine' ? '因子挖掘' : '滚动窗口验证',
      route: 'strategy',
      submit: async () => {
        const r = kind === 'mine' ? await startAlphaMine(params) : await startAlphaWalkforward(params)
        return { job_id: r.job.job_id }
      },
    })
    if (id) openForm.value = false
  } finally {
    starting.value = false
  }
}

// 任务从"运行中"变为"结束"时刷新结果
let wasRunning = false
watch(activeJob, (v) => {
  if (v) wasRunning = true
  else if (wasRunning) { wasRunning = false; load() }
})

// DataTable 的 row 是 Record<string, unknown>，模板里用这两个取值器收窄类型
const tr = (row: unknown) => (((row as AlphaFormula).train_metrics || {}) as Record<string, number>)
const oo = (row: unknown) => (((row as AlphaFormula).oos_metrics || {}) as Record<string, number>)

const fmtPct4 = (v: unknown) => {
  const n = Number(v)
  return Number.isFinite(n) ? (n >= 0 ? '+' : '') + (n * 100).toFixed(2) + '%' : '—'
}
const compFolds = computed(() => comp.value?.folds || [])
const reportUrl = (kind: string) => `${apiBase()}/api/report/${kind}`
const apiBase = () => {
  const env = (import.meta as unknown as { env?: Record<string, string> }).env?.VITE_API_BASE
  return env || 'http://127.0.0.1:5000'
}
const compMean = computed(() => {
  const xs = compFolds.value.map((f) => Number(f.oos_ex) || 0)
  return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : 0
})
const compMedian = computed(() => {
  const xs = compFolds.value.map((f) => Number(f.oos_ex) || 0).sort((a, b) => a - b)
  if (!xs.length) return 0
  const m = Math.floor(xs.length / 2)
  return xs.length % 2 ? xs[m] : (xs[m - 1] + xs[m]) / 2
})
const compPositive = computed(() => compFolds.value.filter((f) => Number(f.oos_ex) > 0).length)
const compSortino = computed(() => {
  const xs = compFolds.value.map((f) => Number(f.oos_sortino) || 0)
  return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : 0
})

const keptFormulas = computed<Record<string, unknown>[]>(() =>
  (current.value?.formulas || [])
    .filter((f) => f.kept && f.rank > 0)
    .sort((a, b) => a.rank - b.rank)
    .map((f) => ({ ...f }) as unknown as Record<string, unknown>))

const combos = computed(() => {
  const s = (current.value?.summary || {}) as { combos?: { k: number; train: Record<string, number>; oos: Record<string, number> }[] }
  return s.combos || []
})
const wfSummary = computed(() => {
  const s = (current.value?.summary || {}) as Record<string, number | null>
  return current.value?.kind === 'walkforward' ? s : null
})
const wfFolds = computed(() => {
  const s = (current.value?.summary || {}) as { folds?: { fold: number; train: string; test: string; kept: string[] }[] }
  return s.folds || []
})

async function loadZoo() {
  try {
    const r = await getAlphaZoo(zooSort.value, 120)
    zoo.value = r.factors || []
    zooMeta.value = r.meta || {}
  } catch (e) {
    toast.error(e instanceof Error ? e.message : String(e))
  }
}

async function loadComposite() {
  try {
    comp.value = await getAlphaCompositeReport()
  } catch (e) {
    toast.error(e instanceof Error ? e.message : String(e))
  }
}

async function loadSmb() {
  try {
    smb.value = await getAlphaSmb()
  } catch (e) {
    toast.error(e instanceof Error ? e.message : String(e))
  }
}

watch(zooSort, loadZoo)

onMounted(async () => { await Promise.all([load(), loadMeta(), loadZoo(), loadComposite(), loadSmb()]) })
</script>

<template>
  <div class="alpha">
    <SectionCard title="因子挖掘" desc="让程序自己写因子公式：公式 = 特征 + 算子，用回测当奖励搜索；样本外不合格的不采纳">
      <template #actions>
        <button class="ui-btn ui-btn--ghost" @click="openForm = !openForm">
          <Icon name="settings" :size="13" /><span>{{ openForm ? '收起参数' : '参数' }}</span>
        </button>
        <button class="ui-btn" :disabled="running || starting" @click="start('mine')">
          <Icon name="play" :size="13" /><span>开始挖掘</span>
        </button>
        <button class="ui-btn ui-btn--ghost" :disabled="running || starting" @click="start('walkforward')">
          <Icon name="refresh" :size="13" /><span>滚动窗口验证</span>
        </button>
      </template>

      <div v-if="running" class="prog">
        <div class="prog__bar"><i :style="{ width: progress + '%' }" /></div>
        <div class="prog__meta">
          <span>{{ progress }}%</span>
          <span class="prog__msg">{{ progressMsg }}</span>
        </div>
      </div>

      <div v-if="openForm" class="form">
        <div class="form__grid">
          <FormField label="股票池（按起点前成交额取 Top）">
            <input v-model.number="form.codes" class="ui-input" type="number" min="50" step="50" />
          </FormField>
          <FormField label="起点"><input v-model="form.start" class="ui-input" /></FormField>
          <FormField label="终点"><input v-model="form.end" class="ui-input" /></FormField>
          <FormField label="种群大小"><input v-model.number="form.pop" class="ui-input" type="number" min="30" step="10" /></FormField>
          <FormField label="迭代代数"><input v-model.number="form.gens" class="ui-input" type="number" min="5" step="5" /></FormField>
          <FormField label="持有天数" hint=">1 用重叠建仓，显著降低换手与成本">
            <input v-model.number="form.hold" class="ui-input" type="number" min="1" max="20" />
          </FormField>
          <FormField label="每日持仓只数"><input v-model.number="form.topk" class="ui-input" type="number" min="5" step="5" /></FormField>
          <FormField label="挖掘 / 验证折数">
            <input v-model.number="form.folds" class="ui-input" type="number" min="2" max="10" />
          </FormField>
        </div>
        <p class="hint">
          特征 {{ meta?.features?.length ?? '—' }} 个 · 算子 {{ meta?.operators?.length ?? '—' }} 个 ·
          公式长度上限 12 · 成本按单边 5bp（佣金+印花税+滑点）
        </p>
      </div>

      <div class="subtabs">
        <button class="subtab" :class="{ 'subtab--on': tab === 'mine' }" @click="tab = 'mine'">挖掘 / 滚动验证</button>
        <button class="subtab" :class="{ 'subtab--on': tab === 'zoo' }" @click="tab = 'zoo'">因子体检榜</button>
        <button class="subtab" :class="{ 'subtab--on': tab === 'composite' }" @click="tab = 'composite'">组合验证（已验证有效）</button>
        <button class="subtab" :class="{ 'subtab--on': tab === 'smb' }" @click="tab = 'smb'">规模因子 SMB（微盘）</button>
      </div>

      <!-- 因子体检榜 -->
      <div v-if="tab === 'zoo'" class="zoo">
        <div class="zoo__bar">
          <span>排序</span>
          <button class="chip" :class="{ 'chip--on': zooSort === 'ic' }" @click="zooSort = 'ic'">|IC|</button>
          <button class="chip" :class="{ 'chip--on': zooSort === 'ic_neutral' }" @click="zooSort = 'ic_neutral'">中性化 IC</button>
          <button class="chip" :class="{ 'chip--on': zooSort === 'ex_ann' }" @click="zooSort = 'ex_ann'">超额年化</button>
          <a class="chip" :href="reportUrl('factor-zoo')" target="_blank" rel="noopener">打开报告</a>
          <span class="zoo__meta">{{ zooMeta.codes }} 只 × {{ zooMeta.days }} 日 · 等权池年化
            {{ ((Number(zooMeta.pool_ann) || 0) * 100).toFixed(1) }}%</span>
        </div>
        <DataTable :rows="zoo" :columns="[
          { key: 'factor', title: '因子' },
          { key: 'ic', title: 'IC', align: 'right' },
          { key: 'ic20', title: 'IC(20日)', align: 'right' },
          { key: 'ic_neutral', title: 'IC(中性)', align: 'right' },
          { key: 'ex_ann', title: '超额年化', align: 'right' },
          { key: 'ex_neutral', title: '超额(中性)', align: 'right' },
          { key: 'ex_sortino', title: 'Sortino', align: 'right' },
          { key: 'maxdd', title: '回撤', align: 'right' },
          { key: 'turnover', title: '换手', align: 'right' },
          { key: 'seg_pos', title: '半年为正', align: 'right' },
        ]">
          <template #cell-ic="{ row }">{{ fmtPct4(row.ic) }}</template>
          <template #cell-ic20="{ row }">{{ fmtPct4(row.ic20) }}</template>
          <template #cell-ic_neutral="{ row }">{{ fmtPct4(row.ic_neutral) }}</template>
          <template #cell-ex_ann="{ row }"><span :class="Number(row.ex_ann) >= 0 ? 'up' : 'down'">{{ fmt(row.ex_ann) }}</span></template>
          <template #cell-ex_neutral="{ row }"><span :class="Number(row.ex_neutral) >= 0 ? 'up' : 'down'">{{ fmt(row.ex_neutral) }}</span></template>
          <template #cell-ex_sortino="{ row }">{{ num(row.ex_sortino) }}</template>
          <template #cell-maxdd="{ row }">{{ fmt(-Math.abs(Number(row.maxdd) || 0)) }}</template>
          <template #cell-turnover="{ row }">{{ num(row.turnover) }}</template>
          <template #cell-seg_pos="{ row }">{{ row.seg_pos }}/{{ Number(row.n_seg) - 1 }}</template>
        </DataTable>
        <p class="hint">
          判读：<b>IC(中性)</b> 是剥离市值/波动风格后的排序预测力，|IC| ≥ 0.005 才算有信号；
          <b>超额(中性)</b> 是 Top-K 组合相对等权池的表现。注意「超额为正但多空价差为负」的因子
          （如低波动类）其实是风格 beta，不是选股能力。
        </p>
      </div>

      <!-- 组合验证 -->
      <div v-else-if="tab === 'composite'" class="comp">
        <div class="zoo__bar">
          <span>已通过 10 折滚动验证（8/10 折样本外为正）</span>
          <a class="chip" :href="reportUrl('composite')" target="_blank" rel="noopener">打开报告</a>
        </div>
        <template v-if="compFolds.length">
          <div class="sum">
            <div class="sum__cell"><span class="k">组合成分</span>
              <span class="v small">{{ (comp?.meta?.components || []).join('  ') }}</span></div>
            <div class="sum__cell"><span class="k">全期 IC / IC_IR</span>
              <span class="v">{{ fmtPct4(comp?.full?.ic) }} / {{ num(comp?.full?.ic_ir) }}</span></div>
            <div class="sum__cell"><span class="k">全期年化 / 超额</span>
              <span class="v">{{ fmt(comp?.full?.ann) }} / {{ fmt(comp?.full?.ex_ann) }}</span></div>
            <div class="sum__cell"><span class="k">样本外超额（均值 / 中位）</span>
              <span class="v">{{ fmt(compMean) }} / {{ fmt(compMedian) }}</span></div>
            <div class="sum__cell"><span class="k">为正折数</span>
              <span class="v">{{ compPositive }}/{{ compFolds.length }}</span></div>
            <div class="sum__cell"><span class="k">平均 Sortino</span>
              <span class="v">{{ num(compSortino) }}</span></div>
          </div>
          <DataTable :rows="compFolds" :columns="[
            { key: 'fold', title: '#', width: '44px' },
            { key: 'test', title: '测试窗口' },
            { key: 'oos_ex', title: '样本外超额', align: 'right' },
            { key: 'oos_sortino', title: 'Sortino', align: 'right' },
            { key: 'oos_ic', title: 'IC', align: 'right' },
            { key: 'oos_dd', title: '回撤', align: 'right' },
          ]">
            <template #cell-oos_ex="{ row }"><span :class="Number(row.oos_ex) >= 0 ? 'up' : 'down'">{{ fmt(row.oos_ex) }}</span></template>
            <template #cell-oos_sortino="{ row }">{{ num(row.oos_sortino) }}</template>
            <template #cell-oos_ic="{ row }">{{ fmtPct4(row.oos_ic) }}</template>
            <template #cell-oos_dd="{ row }">{{ fmt(-Math.abs(Number(row.oos_dd) || 0)) }}</template>
          </DataTable>
          <p class="hint">
            组合 = 等权 rank 合成（无搜索、无挑选偏差），10 折滚动窗口样本外评估。
            结论：短期反转 + 小市值 + 远离 60 日高点在本土数据上稳定为正；
            低波动类因子在同期是<b>反向</b>的（高波动占优），已从组合中剔除。
          </p>
        </template>
        <EmptyGuide v-else title="还没有组合验证报告"
          desc="运行 python -m backend.alpha.composite_test 生成（约 40 秒，纯本地计算）" />
      </div>

      <!-- 规模因子 SMB -->
      <div v-else-if="tab === 'smb'" class="comp">
        <template v-if="smb?.summary">
          <div class="zoo__bar">
            <span>每月末选流通市值最小的 5 只、等权持有一个月（已剔除 ST/退市代理，单边成本 0.3%）</span>
            <a class="chip" :href="reportUrl('smb')" target="_blank" rel="noopener">打开报告</a>
          </div>
          <div class="sum">
            <div class="sum__cell"><span class="k">年化</span><span class="v up">{{ fmt(smb.summary.ann) }}</span></div>
            <div class="sum__cell"><span class="k">累计</span><span class="v up">{{ fmt(smb.summary.total) }}</span></div>
            <div class="sum__cell"><span class="k">夏普</span><span class="v">{{ num(smb.summary.sharpe) }}</span></div>
            <div class="sum__cell"><span class="k">最大回撤</span><span class="v down">{{ fmt(-Math.abs(Number(smb.summary.maxdd) || 0)) }}</span></div>
            <div class="sum__cell"><span class="k">月胜率</span><span class="v">{{ num(smb.summary.month_win) }}</span></div>
            <div class="sum__cell"><span class="k">月均 t 值</span><span class="v">{{ num(smb.summary.t_stat) }}</span></div>
            <div class="sum__cell"><span class="k">对照：等权全市场</span><span class="v">{{ fmt(smb.benchmark?.ann) }}</span></div>
            <div class="sum__cell"><span class="k">SMB（小100−大100）年化</span><span class="v">{{ fmt(smb.smb?.ann) }}（t={{ num(smb.smb?.t_stat) }}）</span></div>
          </div>
          <div class="combo">
            <div class="combo__title">成本敏感性（单边成本 → 年化）——微盘策略的生死线</div>
            <div class="combo__row">
              <span v-for="c in smb.cost_curve || []" :key="c.cost_one_way">
                {{ (c.cost_one_way * 100).toFixed(1) }}% → <b :class="c.ann >= 0 ? 'up' : 'down'">{{ fmt(c.ann) }}</b>
              </span>
            </div>
          </div>
          <div class="combo">
            <div class="combo__title">再加一个维度能不能提升？（同成本口径，rank 加权）</div>
            <div class="combo__row">
              <span v-for="c in smb.tilt_compare || []" :key="c.name">
                {{ c.name }} <b :class="c.ann >= 0 ? 'up' : 'down'">{{ fmt(c.ann) }}</b>（t={{ num(c.t_stat) }}）
              </span>
            </div>
          </div>
          <p class="hint">
            结论：这个因子本质是**微盘效应**——宽口径的 SMB（小100−大100）不显著（t≈0.3），
            收益全在“最小的 5 只”；叠加动量/波动/位置等第二维度**没有稳定改善**（唯一持平的是再剔除高换手）。
            平均持仓流通市值仅 2.4 亿元，实盘冲击成本若达 1% 年化就只剩 +0.7%，因此把它当“可研究、慎实盘”的因子看待。
          </p>
        </template>
        <EmptyGuide v-else title="还没有规模因子回测结果"
          desc="运行 python -m backend.alpha.smb --top 5 --cost 0.003 --compare-tilts 生成" />
      </div>

      <LoadingBlock v-else-if="loading && !runs.length" />
      <EmptyGuide v-else-if="!runs.length" title="还没有挖掘记录"
        desc="点「开始挖掘」跑第一次（默认 300 只 × 4 年，约 3~5 分钟，纯本地计算不调用大模型）" />

      <template v-else>
        <div class="runs">
          <span class="runs__label">历史运行</span>
          <button v-for="r in runs" :key="r.id" class="chip"
            :class="{ 'chip--on': current?.id === r.id }" @click="select(r.id)">
            #{{ r.id }} {{ r.kind === 'mine' ? '挖掘' : '滚动验证' }}
            <span class="chip__st" :class="r.status">{{ r.status === 'done' ? '完成' : r.status === 'error' ? '失败' : '进行中' }}</span>
          </button>
        </div>

        <div v-if="current" class="detail">
          <div class="kv">
            <span>股票池 {{ metaOf(current).codes ?? '—' }} 只</span>
            <span>{{ metaOf(current).start }} ~ {{ metaOf(current).end }}</span>
            <span>持有 {{ metaOf(current).hold ?? 1 }} 天</span>
            <span>求值 {{ metaOf(current).evaluations ?? '—' }} 次</span>
            <span>用时 {{ metaOf(current).elapsed_sec ?? '—' }}s</span>
            <span v-if="current.kind === 'mine'">基准年化 训练 {{ fmt(metaOf(current).bench_ann_train) }} / 样本外 {{ fmt(metaOf(current).bench_ann_oos) }}</span>
          </div>
          <p v-if="current.error" class="err">失败原因：{{ current.error }}</p>

          <!-- 滚动验证汇总 -->
          <template v-if="wfSummary">
            <div class="sum">
              <div class="sum__cell"><span class="k">折数</span><span class="v">{{ wfSummary.n_folds }}</span></div>
              <div class="sum__cell"><span class="k">单公式 样本外超额（均值）</span>
                <span class="v" :class="(wfSummary.best_mean_ex_ann ?? 0) >= 0 ? 'up' : 'down'">{{ fmt(wfSummary.best_mean_ex_ann) }}</span></div>
              <div class="sum__cell"><span class="k">Top5 合成 样本外超额（均值）</span>
                <span class="v" :class="(wfSummary.combo_mean_ex_ann ?? 0) >= 0 ? 'up' : 'down'">{{ fmt(wfSummary.combo_mean_ex_ann) }}</span></div>
              <div class="sum__cell"><span class="k">为正折数</span>
                <span class="v">{{ wfSummary.combo_positive_folds }}/{{ wfSummary.n_folds }}</span></div>
              <div class="sum__cell"><span class="k">超额 Sortino（均值）</span>
                <span class="v">{{ num(wfSummary.combo_mean_ex_sortino) }}</span></div>
              <div class="sum__cell"><span class="k">IC（均值）</span>
                <span class="v">{{ Number(wfSummary.combo_mean_ic ?? 0).toFixed(4) }}</span></div>
            </div>
          </template>

          <!-- 挖掘结果：保留的公式 -->
          <DataTable v-if="keptFormulas.length" :rows="keptFormulas" :columns="[
            { key: 'rank', title: '#', width: '44px' },
            { key: 'formula', title: '公式' },
            { key: 'train', title: '训练 超额年化', align: 'right' },
            { key: 'oos', title: '样本外 超额年化', align: 'right' },
            { key: 'ic', title: 'IC / IC_IR', align: 'right' },
            { key: 'dd', title: '回撤', align: 'right' },
            { key: 'turnover', title: '换手', align: 'right' },
          ]">
            <template #cell-formula="{ row }"><code class="fx">{{ row.formula }}</code></template>
            <template #cell-train="{ row }">
              <span :class="(tr(row).ex_ann ?? 0) >= 0 ? 'up' : 'down'">{{ fmt(tr(row).ex_ann) }}</span>
            </template>
            <template #cell-oos="{ row }">
              <span :class="(oo(row).ex_ann ?? 0) >= 0 ? 'up' : 'down'">{{ fmt(oo(row).ex_ann) }}</span>
            </template>
            <template #cell-ic="{ row }">
              {{ Number(oo(row).ic ?? 0).toFixed(4) }} / {{ num(oo(row).ic_ir) }}
            </template>
            <template #cell-dd="{ row }">{{ fmt(-Math.abs(Number(oo(row).maxdd ?? 0))) }}</template>
            <template #cell-turnover="{ row }">{{ num(oo(row).turnover) }}</template>
          </DataTable>

          <!-- 多因子合成对照 -->
          <div v-if="combos.length" class="combo">
            <div class="combo__title">多因子合成（等权 rank 合成，最接近实际用法）</div>
            <div v-for="c in combos" :key="c.k" class="combo__row">
              <span class="combo__k">Top{{ c.k }}</span>
              <span>训练 超额 {{ fmt(c.train?.ex_ann) }}（Sortino {{ num(c.train?.ex_sortino) }}）</span>
              <span>样本外 超额 <b :class="(c.oos?.ex_ann ?? 0) >= 0 ? 'up' : 'down'">{{ fmt(c.oos?.ex_ann) }}</b>
                （Sortino {{ num(c.oos?.ex_sortino) }} · IC {{ Number(c.oos?.ic ?? 0).toFixed(4) }} · 回撤 {{ fmt(-Math.abs(Number(c.oos?.maxdd ?? 0))) }}）</span>
            </div>
          </div>

          <p class="hint">
            口径说明：目标是 open-to-open（t 日信号 → t+1 开盘买 → t+1+持有天数 开盘卖），
            组合为每日按因子值取 Top-K 等权；「超额」= 相对等权股票池。
            IC ≈ 0.00x 时说明排序预测力弱、收益集中在头部几只，实盘前请再做滚动验证。
          </p>
        </div>
      </template>
    </SectionCard>
  </div>
</template>

<style scoped>
.alpha { display: flex; flex-direction: column; gap: 12px; }
.subtabs { display: flex; gap: 6px; margin: 10px 0 4px; }
.subtab { padding: 4px 12px; border-radius: 999px; border: 1px solid var(--border); background: var(--panel);
  color: var(--text-sub); font-size: var(--fs-xs); cursor: pointer; }
.subtab--on { border-color: var(--accent); color: var(--accent); }
.zoo { display: flex; flex-direction: column; gap: 8px; }
.zoo__bar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: var(--fs-xs); color: var(--text-faint); }
.zoo__meta { margin-left: auto; }
.comp { display: flex; flex-direction: column; gap: 10px; }
.sum__cell .v.small { font-size: var(--fs-xs); font-weight: 500; }
.prog { display: flex; flex-direction: column; gap: 6px; margin: 10px 0 2px; }
.prog__bar { height: 6px; border-radius: 999px; background: var(--panel-2); overflow: hidden; }
.prog__bar i { display: block; height: 100%; background: var(--accent); transition: width .3s; }
.prog__meta { display: flex; gap: 10px; font-size: var(--fs-xs); color: var(--text-sub); }
.prog__msg { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.form { margin-top: 10px; padding: 12px; border-radius: var(--radius-sm); background: var(--panel-2); }
.form__grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 10px; }
.runs { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin-top: 10px; }
.runs__label { font-size: var(--fs-xs); color: var(--text-faint); margin-right: 4px; }
.chip { display: inline-flex; align-items: center; gap: 6px; padding: 3px 10px; border-radius: 999px;
  border: 1px solid var(--border); background: var(--panel); color: var(--text-sub); font-size: var(--fs-xs); cursor: pointer; }
.chip--on { border-color: var(--accent); color: var(--accent); }
.chip__st.done { color: var(--ok, var(--accent)); }
.chip__st.error { color: var(--down, var(--accent)); }
.detail { margin-top: 12px; display: flex; flex-direction: column; gap: 10px; }
.kv { display: flex; flex-wrap: wrap; gap: 14px; font-size: var(--fs-xs); color: var(--text-faint); }
.sum { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 1px;
  background: var(--border); border-radius: var(--radius-sm); overflow: hidden; }
.sum__cell { display: flex; flex-direction: column; gap: 4px; padding: 10px 14px; background: var(--panel); }
.sum__cell .k { font-size: var(--fs-xs); color: var(--text-faint); }
.sum__cell .v { font-size: var(--fs-sm); font-weight: 700; }
.combo { display: flex; flex-direction: column; gap: 6px; padding: 12px; border-radius: var(--radius-sm); background: var(--panel-2); }
.combo__title { font-size: var(--fs-xs); font-weight: 700; color: var(--text-sub); }
.combo__row { display: flex; flex-wrap: wrap; gap: 14px; font-size: var(--fs-xs); color: var(--text-sub); }
.combo__k { font-weight: 700; color: var(--accent); }
.fx { font-family: var(--font-mono, monospace); font-size: var(--fs-xs); color: var(--accent); word-break: break-all; }
.err { font-size: var(--fs-xs); color: var(--down, var(--accent)); }
.hint { font-size: var(--fs-xs); color: var(--text-faint); line-height: 1.7; margin: 0; }
</style>
