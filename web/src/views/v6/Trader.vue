<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import SectionCard from '@/components/ui/SectionCard.vue'
import StatTile from '@/components/ui/StatTile.vue'
import EmptyGuide from '@/components/ui/EmptyGuide.vue'
import LoadingBlock from '@/components/ui/LoadingBlock.vue'
import Drawer from '@/components/ui/Drawer.vue'
import FormField from '@/components/ui/FormField.vue'
import Icon from '@/components/Icon.vue'
import { useToastStore } from '@/stores/toast'
import { useJobsStore } from '@/stores/jobs'
import {
  getTraderState, getTraderDecisions, getTraderMemory, toggleTraderMemory,
  updateTraderProfile, runTrader, getTraderOutlook,
} from '@/api'
import type { TraderState, TraderDecision, TraderMemory, TraderOutlookStats } from '@/api'

const toast = useToastStore()
const jobs = useJobsStore()

const props = withDefaults(defineProps<{ profileId?: number }>(), { profileId: undefined })

const state = ref<TraderState | null>(null)
const decisions = ref<TraderDecision[]>([])
const memory = ref<TraderMemory[]>([])
const styleMem = ref<TraderMemory | null>(null)
const loading = ref(true)
const error = ref('')
const memKind = ref<'style' | 'thesis' | 'lesson' | 'note'>('style')
const outlook = ref<TraderOutlookStats | null>(null)

/** 最新决策的自洽性提示 */
const latestCoherence = computed(() => {
  const d = decisions.value[0] as unknown as { coherence?: { level?: string; kind?: string; msg: string }[] } | undefined
  const list = d?.coherence || []
  return Array.isArray(list) ? list : []
})

/** 最新决策里的编号闸门（系统判定的部分） */
const latestGateList = computed(() => {
  const d = decisions.value[0] as unknown as { gates?: { gates?: unknown[] } } | undefined
  const list = (d?.gates?.gates || []) as { id: string; title: string; kind: string; status: string; note?: string; facts?: Record<string, unknown> }[]
  return Array.isArray(list) ? list : []
})

/** 闸门事实压成一行摘要（数字多的字段只取前几个键值） */
function summarizeFacts(facts?: Record<string, unknown>): string {
  if (!facts) return ''
  return Object.entries(facts)
    .filter(([, v]) => v !== null && v !== undefined && v !== '' && typeof v !== 'object')
    .slice(0, 5)
    .map(([k, v]) => `${k}=${v}`)
    .join(' · ')
}
const expanded = ref<Record<string, boolean>>({})
const settingsOpen = ref(false)
const saving = ref(false)

// 设置草稿（仅自动开关；风格与仓位全由 AI 自定）
const draft = ref({ enabled: 1 })

const runningJob = computed(() => jobs.activeByKind('trader'))
const isRunning = computed(() => !!runningJob.value)
/** 操盘手任务完成信号（用于决策结束后刷新页面） */
const doneSignal = computed(() =>
  jobs
    .byKind('trader')
    .map((j) => `${j.id}:${j.doneTick || 0}:${j.status}`)
    .join('|'),
)

async function load() {
  error.value = ''
  try {
    const st = await getTraderState(props.profileId)
    state.value = st
    draft.value = { enabled: st.profile.enabled }
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
}

async function loadLists() {
  try {
    const [d, m, s] = await Promise.all([
      getTraderDecisions(30, 0, props.profileId),
      getTraderMemory(memKind.value, true, props.profileId),
      getTraderMemory('style', true, props.profileId),
    ])
    decisions.value = d.items
    memory.value = m.items
    styleMem.value = s.items[0] || null
    if (props.profileId) outlook.value = await getTraderOutlook(props.profileId, 60).catch(() => null)
  } catch {
    /* 列表失败不阻塞主视图 */
  }
}

async function reloadAll() {
  await load()
  await loadLists()
}

onMounted(reloadAll)

watch(memKind, loadLists)
watch(doneSignal, (v, old) => {
  if (v !== old) reloadAll()
})

function runNow() {
  if (isRunning.value) return
  jobs.run({
    kind: 'trader',
    title: 'AI 操盘手决策',
    submit: () => runTrader({ force: true, profile_id: props.profileId }),
    route: '/ai?tab=trader',
  })
}

async function saveSettings() {
  saving.value = true
  try {
    await updateTraderProfile(props.profileId ?? 0, { enabled: draft.value.enabled })
    toast.success('已保存')
    settingsOpen.value = false
    await load()
  } catch (e) {
    toast.error('保存失败：' + (e instanceof Error ? e.message : String(e)))
  } finally {
    saving.value = false
  }
}

async function toggleMem(m: TraderMemory) {
  try {
    await toggleTraderMemory(m.id, !m.active)
    m.active = m.active ? 0 : 1
  } catch (e) {
    toast.error('操作失败：' + (e instanceof Error ? e.message : String(e)))
  }
}

// ── 展示辅助 ──
const latest = computed(() => state.value?.today_decision || state.value?.latest_decision || null)

// 选股方式：AI 操盘手默认自主选股（模型自己检索市场），也可配置为固定口径
const selectionMode = computed(() => {
  const meta = ((state.value?.profile || {}) as { meta?: Record<string, unknown> }).meta || {}
  const sel = String(meta.selection || 'self')
  if (sel === 'composite') return '因子组合口径（-1日反转/-5日反转/-远离60日高点/-小市值）'
  if (sel === 'smallcap') return '小盘动量评分卡（规模×历史涨跌幅）'
  if (sel === 'scorecard') return '评分卡口径（五组加权）'
  return '自主选股（模型自己检索市场）'
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
function sideLabel(s: string) {
  return s === 'buy' ? '买入' : '卖出'
}
function actionSummary(d: TraderDecision) {
  const n = d.plan?.length || 0
  if (!n) return '保持现状'
  return d.plan.map((o) => `${sideLabel(o.side)} ${o.name || o.code} ${o.qty}股`).join(' · ')
}
function navDelta(d: TraderDecision) {
  if (d.nav_before == null || d.nav_after == null) return null
  return (d.nav_after - d.nav_before) * 100
}
function navTone(d: TraderDecision): 'up' | 'down' | 'flat' {
  const v = navDelta(d)
  if (v == null || Math.abs(v) < 0.005) return 'flat'
  return v > 0 ? 'up' : 'down'
}
function toggleExpand(key: string) {
  expanded.value[key] = !expanded.value[key]
}
function execOf(d: TraderDecision, i: number) {
  return (d.executions || [])[i]
}

const KIND_LABEL: Record<string, string> = {
  style: '自我风格', thesis: '持仓逻辑', lesson: '经验教训', note: '观察笔记',
}

const TOOL_LABEL: Record<string, string> = {
  get_account_summary: '查看账户', get_positions: '查看持仓', get_stock_price: '查价格',
  search_stock: '搜索股票', get_market_news: '读市场快讯', get_stock_news: '读个股新闻',
  get_regime: '看市场环境', get_candidates: '看候选股', preview_order: '预检委托',
  place_order: '下单', cancel_order: '撤单', remember: '记长期记忆', submit_decision: '结束决策',
}
function toolLine(t: { tool: string; args?: Record<string, unknown>; error?: string }) {
  const label = TOOL_LABEL[t.tool] || t.tool
  const a = t.args || {}
  if (t.tool === 'place_order') {
    const side = a.side === 'buy' ? '买入' : '卖出'
    return `${label} ${side} ${a.code} ${a.qty}${t.error ? ' → ' + t.error : ''}`
  }
  if (['get_stock_price', 'get_stock_news', 'search_stock'].includes(t.tool) && a.code) {
    return `${label} ${a.code}${t.error ? ' → ' + t.error : ''}`
  }
  return `${label}${t.error ? ' → ' + t.error : ''}`
}
</script>

<template>
  <div class="trader">
    <LoadingBlock v-if="loading && !state" :rows="5" />

    <EmptyGuide v-else-if="error && !state" icon="alert" title="加载失败" :desc="error">
      <template #action><button class="ui-btn" @click="reloadAll">重试</button></template>
    </EmptyGuide>

    <template v-else-if="state">
      <!-- 顶部：账户 + 操作 -->
      <div class="metrics">
        <StatTile label="账户总资产" :value="fmtMoney(state.summary.total_assets)" icon="wallet" />
        <StatTile
          label="累计盈亏"
          :value="fmtMoney(state.summary.total_profit)"
          :trend="state.summary.total_profit >= 0 ? 'up' : 'down'"
          :hint="fmtPct(state.summary.total_profit_pct)"
          :hint-trend="state.summary.total_profit >= 0 ? 'up' : 'down'"
        />
        <StatTile label="持仓" :value="state.summary.positions" unit="只" />
        <StatTile label="可用资金" :value="fmtMoney(state.summary.balance)" />
        <StatTile label="长期记忆" :value="state.memory_count" unit="条" icon="chat" />
      </div>

      <div class="bar">
        <div class="bar__meta">
          <span class="dot" :class="state.profile.enabled ? 'dot--ok' : 'dot--off'" />
          <span>{{ state.profile.enabled ? '自动决策已开启' : '自动决策已停用' }}</span>
          <span class="sep">·</span>
          <span>每日数据更新后自动决策</span>
          <span class="sep">·</span>
          <span>{{ state.llm_configured ? `模型 ${state.model || '已配置'}` : '未配置大模型' }}</span>
          <span class="sep">·</span>
          <span>交易规则由模拟券商系统强制执行</span>
        </div>
        <div class="bar__actions">
          <button class="ui-btn" @click="settingsOpen = true"><Icon name="settings" :size="14" /><span>设置</span></button>
          <button class="ui-btn ui-btn--primary" :disabled="isRunning || !state.llm_configured" @click="runNow">
            <Icon name="play" :size="14" /><span>{{ isRunning ? '决策中…' : '立即决策' }}</span>
          </button>
        </div>
      </div>

      <!-- 运行进度 -->
      <div v-if="isRunning" class="progress">
        <div class="progress__bar"><div class="progress__fill" :style="{ width: (runningJob?.pct || 0) + '%' }" /></div>
        <div class="progress__msg">{{ runningJob?.msg || '执行中…' }}</div>
      </div>

      <!-- 自我风格 -->
      <SectionCard title="选股方式" desc="AI 操盘手与回测/选股程序是分开的：默认由模型自己检索市场">
        <div class="kv">
          <span class="kv__k">当前模式</span><span class="kv__v">{{ selectionMode }}</span>
        </div>
        <p class="muted" style="margin-top:8px;font-size:var(--fs-xs);line-height:1.7">
          自主选股模式下，系统**不再**预置候选池；模型用 screen_stocks 按市值/涨跌幅/换手/振幅/波动/位置等维度
          自行筛选排序，再用 get_stock_factors 验证后下单，筛选条件与顺序会写进当日思考（可审计）。
          可在档案 meta.selection 里改为 scorecard / composite / smallcap 使用固定口径。
        </p>
      </SectionCard>

      <SectionCard title="AI 自我风格" desc="由操盘手在长期决策中自行形成与修正">
        <p v-if="styleMem" class="prose">{{ styleMem.content }}</p>
        <p v-else class="prose prose--sub">
          尚未形成。没有预设人设与仓位限制，AI 会在每日决策中逐步形成自己的风格，并写进长期记忆。
        </p>
      </SectionCard>

      <!-- 今日/最近决策 -->
      <!-- 自洽性提示：模型自己的说法与动作是否一致 -->
      <SectionCard v-if="latestCoherence.length" title="自洽性提示"
        desc="模型的说法与动作对不上时程序会点出来（提示而非拒绝，便于事后复盘）">
        <div class="kv" v-for="(c, i) in latestCoherence" :key="i">
          <span class="kv__k">{{ c.kind === 'outlook_vs_orders' ? '预测 vs 委托' : c.kind === 'claim_vs_orders' ? '说法 vs 委托' : '其他' }}</span>
          <span class="kv__v">{{ c.msg }}</span>
        </div>
      </SectionCard>

      <!-- 今日闸门：编号决策协议（系统判定的部分） -->
      <SectionCard v-if="latestGateList.length" title="今日闸门"
        desc="编号决策协议：能计算的部分由系统判定，模型只回答 [你] 的闸门（可审计）">
        <div class="gates">
          <div v-for="g in latestGateList" :key="g.id" class="gate" :class="'gate--' + g.status">
            <span class="gate__id">{{ g.id }}</span>
            <span class="gate__title">{{ g.title }}</span>
            <span class="gate__kind">{{ g.kind === 'code' ? '系统' : '你' }}</span>
            <span class="gate__note">{{ g.note || summarizeFacts(g.facts) }}</span>
          </div>
        </div>
      </SectionCard>

      <!-- 预测校准：每日"次日净值方向 + 置信度" vs 真实结果 -->
      <SectionCard v-if="outlook && outlook.n > 0" title="预测校准"
        desc="它每天给出的「次日方向 + 置信度」与真实净值对账 —— 比总收益更能区分运气与能力">
        <div class="metrics" style="padding:0; background:none; border:none">
          <StatTile label="已结算预测" :value="outlook.n" unit="次" />
          <StatTile label="命中率" :value="outlook.hit_rate != null ? outlook.hit_rate + '%' : '—'"
            :hint="'随机基线 ' + outlook.baseline_hit + '%（涨/跌/平三分类）'" />
          <StatTile label="方向性命中率" :value="outlook.hit_rate_directional != null ? outlook.hit_rate_directional + '%' : '—'"
            :hint="`排除「看平」的 ${outlook.n_directional || 0} 次预测（更诚实）`" />
          <StatTile label="Brier 分数" :value="outlook.brier != null ? outlook.brier.toFixed(3) : '—'"
            hint="越低越好（0=完美，>0.66 比乱猜差）" />
        </div>
        <div v-if="outlook.buckets.length" class="kv" style="margin-top:10px">
          <span class="kv__k">按置信度</span>
          <span class="kv__v">
            <span v-for="b in outlook.buckets" :key="b.label" style="margin-right:12px">
              {{ b.label }}：<b>{{ b.hit_rate }}%</b>（{{ b.n }} 次，均值 {{ b.avg_conf }}%）
            </span>
          </span>
        </div>
        <div v-if="outlook.by_direction.length" class="kv">
          <span class="kv__k">按方向</span>
          <span class="kv__v">
            <span v-for="d in outlook.by_direction" :key="d.direction" style="margin-right:12px">
              {{ d.label }}：<b>{{ d.hit_rate }}%</b>（{{ d.n }} 次）
            </span>
          </span>
        </div>
        <div class="table-wrap" style="margin-top:10px">
          <table class="tbl">
            <thead><tr><th>日期</th><th>预测</th><th>置信度</th><th>实际</th><th>结果</th></tr></thead>
            <tbody>
              <tr v-for="r in outlook.recent.slice(0, 8)" :key="r.date">
                <td class="mono">{{ r.date }}</td>
                <td>{{ r.predicted === 'up' ? '看涨' : r.predicted === 'down' ? '看跌' : '看平' }}</td>
                <td class="num">{{ r.confidence }}%</td>
                <td class="num" :class="r.actual_pct >= 0 ? 'up' : 'down'">
                  {{ r.actual === 'up' ? '涨' : r.actual === 'down' ? '跌' : '平' }} {{ r.actual_pct }}%
                </td>
                <td>
                  <span class="ui-chip" :class="r.hit ? 'ui-chip--down' : 'ui-chip--up'">
                    {{ r.hit ? '命中' : '未中' }}
                  </span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-if="outlook.calibration?.n" class="kv" style="margin-top:10px">
          <span class="kv__k">置信度可信度</span>
          <span class="kv__v">
            原始 ECE <b>{{ outlook.calibration.raw_ece }}</b>
            <template v-if="outlook.calibration.calibrated_ece != null">
              → 校准后 <b>{{ outlook.calibration.calibrated_ece }}</b>
            </template>
            （ECE 越低越好；校准后明显更低 = 系统性过度自信）
          </span>
        </div>
        <div v-if="outlook.calibration?.discrimination?.ok" class="kv">
          <span class="kv__k">区分度</span>
          <span class="kv__v">
            低置信组命中 {{ outlook.calibration.discrimination.low_bin_hit }}% ／
            高置信组 {{ outlook.calibration.discrimination.high_bin_hit }}%
            （差 {{ outlook.calibration.discrimination.spread }}pp）—— {{ outlook.calibration.discrimination.note }}
          </span>
        </div>
        <div v-if="outlook.calibration?.gate?.ok" class="kv">
          <span class="kv__k">门槛参考</span>
          <span class="kv__v">
            置信度 ≥ {{ outlook.calibration.gate.threshold }}% 时命中 {{ outlook.calibration.gate.hit_rate }}%
            （整体 {{ outlook.calibration.gate.baseline_hit }}%，提升 {{ outlook.calibration.gate.lift }}pp）
            —— {{ outlook.calibration.gate.note }}
          </span>
        </div>
        <div v-if="outlook.calibration?.reliability?.length" class="table-wrap" style="margin-top:8px">
          <table class="tbl">
            <thead><tr><th>置信度区间</th><th>样本</th><th>声称</th><th>实际命中</th></tr></thead>
            <tbody>
              <tr v-for="r in outlook.calibration.reliability" :key="r.bin">
                <td>{{ r.bin }}</td><td class="num">{{ r.n }}</td>
                <td class="num">{{ r.claimed }}%</td>
                <td class="num" :class="r.actual >= r.claimed ? 'up' : 'down'">{{ r.actual }}%</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-if="outlook.abstain_rate != null" class="kv">
          <span class="kv__k">弃权率</span>
          <span class="kv__v">{{ outlook.abstain_rate }}%（{{ outlook.abstained }} 次；弃权不计命中，也不算"看不清"的失败）</span>
        </div>
        <p class="muted small" style="margin-top:8px">{{ outlook.note }}</p>
      </SectionCard>

      <SectionCard title="最新决策" :desc="latest ? `${latest.trade_date} · ${latest.trigger === 'auto' ? '自动' : '手动'} · ${latest.status === 'done' ? '已完成' : latest.status}` : ''">
        <template #actions>
          <button class="ui-btn ui-btn--ghost" @click="reloadAll"><Icon name="refresh" :size="13" /><span>刷新</span></button>
        </template>

        <EmptyGuide
          v-if="!latest"
          icon="chat"
          title="还没有决策记录"
          desc="数据更新后会自动生成第一次决策，也可以点右上角「立即决策」马上跑一次。"
        />

        <div v-else class="decision">
          <div v-if="latest.error" class="alert">{{ latest.error }}</div>

          <div class="decision__row">
            <span class="tag" :class="latest.plan?.length ? 'tag--act' : 'tag--hold'">
              {{ latest.plan?.length ? `${latest.plan.length} 笔操作` : '保持现状' }}
            </span>
            <span v-if="navDelta(latest) != null" class="navchg" :class="navTone(latest)">
              净值 {{ fmtPct(navDelta(latest)) }}
            </span>
            <span class="muted">{{ latest.finished_at || latest.created_at }}</span>
          </div>

          <div class="block">
            <div class="block__title">思考过程</div>
            <p class="prose">{{ latest.thinking || '—' }}</p>
          </div>

          <div v-if="latest.plan?.length" class="block">
            <div class="block__title">委托与执行</div>
            <table class="mini">
              <thead>
                <tr><th>股票</th><th>方向</th><th class="ta-r">数量</th><th class="ta-r">价格</th><th>结果</th></tr>
              </thead>
              <tbody>
                <tr v-for="(o, i) in latest.plan" :key="i">
                  <td>{{ o.name || o.code }}<span class="muted"> {{ o.code }}</span></td>
                  <td :class="o.side === 'buy' ? 'up' : 'down'">{{ sideLabel(o.side) }}</td>
                  <td class="ta-r">{{ o.qty }}</td>
                  <td class="ta-r">{{ o.price || execOf(latest, i)?.price || '市价' }}</td>
                  <td>
                    <span v-if="execOf(latest, i)?.ok" class="ok">{{ execOf(latest, i)?.detail }}</span>
                    <span v-else class="bad">{{ execOf(latest, i)?.detail || '未执行' }}</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <div v-if="latest.reflection" class="block">
            <div class="block__title">复盘</div>
            <p class="prose">{{ latest.reflection }}</p>
          </div>

          <div v-if="latest.trace?.length" class="block">
            <button class="collapse" @click="toggleExpand('trace')">
              <Icon :name="expanded['trace'] ? 'chevron-down' : 'chevron-right'" :size="13" />
              <span>工具调用（{{ latest.trace.length }} 步）</span>
            </button>
            <div v-if="expanded['trace']" class="trace">
              <div v-for="(t, i) in latest.trace" :key="i" class="trace__item" :class="{ 'is-err': t.error }">
                <span class="trace__idx">{{ i + 1 }}</span>
                <span>{{ toolLine(t) }}</span>
              </div>
            </div>
          </div>

          <div v-if="latest.news?.market?.length || latest.news?.stocks?.length" class="block">
            <button class="collapse" @click="toggleExpand('news')">
              <Icon :name="expanded['news'] ? 'chevron-down' : 'chevron-right'" :size="13" />
              <span>当日新闻要点（{{ (latest.news?.market?.length || 0) + (latest.news?.stocks?.reduce((s, x) => s + x.news.length, 0) || 0) }} 条）</span>
            </button>
            <div v-if="expanded['news']" class="news">
              <div v-if="latest.news?.market?.length" class="news__group">
                <div class="news__label">市场快讯</div>
                <div v-for="(n, i) in latest.news.market.slice(0, 12)" :key="i" class="news__item">
                  <span class="news__time">{{ (n.time || '').slice(5, 16) }}</span>
                  <a v-if="n.url" :href="n.url" target="_blank" rel="noreferrer">{{ n.title }}</a>
                  <span v-else>{{ n.title }}</span>
                </div>
              </div>
              <div v-for="g in latest.news?.stocks || []" :key="g.code" class="news__group">
                <div class="news__label">{{ g.name || g.code }}</div>
                <div v-for="(n, i) in g.news" :key="i" class="news__item">
                  <span class="news__time">{{ (n.time || '').slice(5, 16) }}</span>
                  <a v-if="n.url" :href="n.url" target="_blank" rel="noreferrer">{{ n.title }}</a>
                  <span v-else>{{ n.title }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </SectionCard>

      <!-- 历史决策 -->
      <SectionCard title="历史决策" :desc="`共 ${decisions.length} 条`" :padded="false">
        <EmptyGuide v-if="!decisions.length" icon="calendar" title="暂无历史" desc="决策记录会按交易日累积。" />
        <div v-else class="timeline">
          <div v-for="d in decisions" :key="d.id" class="tl-item">
            <div class="tl-head" @click="toggleExpand('d' + d.id)">
              <span class="tl-date">{{ d.trade_date }}</span>
              <span class="tag tag--sm" :class="d.plan?.length ? 'tag--act' : 'tag--hold'">
                {{ actionSummary(d) }}
              </span>
              <span v-if="navDelta(d) != null" class="tl-nav" :class="navTone(d)">
                {{ fmtPct(navDelta(d)) }}
              </span>
              <span class="tl-status" :class="d.status">{{ d.status === 'done' ? '已完成' : d.status === 'error' ? '失败' : d.status }}</span>
              <Icon class="tl-chev" :name="expanded['d' + d.id] ? 'chevron-down' : 'chevron-right'" :size="14" />
            </div>
            <div v-if="expanded['d' + d.id]" class="tl-body">
              <p class="prose">{{ d.thinking || '—' }}</p>
              <p v-if="d.reflection" class="prose prose--sub">复盘：{{ d.reflection }}</p>
            </div>
          </div>
        </div>
      </SectionCard>

      <!-- 长期记忆 -->
      <SectionCard title="长期记忆" desc="操盘手自己写下的持仓逻辑与经验">
        <template #actions>
          <div class="seg">
            <button
              v-for="k in (['style', 'thesis', 'lesson', 'note'] as const)"
              :key="k"
              class="seg__btn"
              :class="{ 'is-on': memKind === k }"
              @click="memKind = k"
            >{{ KIND_LABEL[k] }}</button>
          </div>
        </template>
        <EmptyGuide v-if="!memory.length" icon="chat" title="暂无记忆" desc="操盘手会在决策时写入持仓逻辑与经验。" />
        <div v-else class="mem">
          <div v-for="m in memory" :key="m.id" class="mem__item" :class="{ 'is-off': !m.active }">
            <div class="mem__head">
              <span v-if="m.code" class="mem__code">{{ m.code }}</span>
              <span v-if="m.regime" class="memregime" :title="`写下这条经验时的市场环境：${m.regime}`">{{ m.regime }}</span>
              <span class="mem__time">{{ m.created_at }}</span>
              <button class="mem__toggle" @click="toggleMem(m)">{{ m.active ? '停用' : '恢复' }}</button>
            </div>
            <p class="mem__body">{{ m.content }}</p>
          </div>
        </div>
      </SectionCard>
    </template>

    <!-- 设置抽屉 -->
    <Drawer :open="settingsOpen" title="操盘手设置" desc="风格与仓位全由 AI 自行判断" :width="420" @update:open="settingsOpen = $event">
      <div class="form">
        <FormField label="自动决策">
          <label class="switch">
            <input v-model="draft.enabled" type="checkbox" :true-value="1" :false-value="0" />
            <span>每日数据更新后自动跑一次决策（并自动下单）</span>
          </label>
        </FormField>
        <div class="hard">
          <div class="hard__title">交易系统（模拟券商）</div>
          <ul class="hard__list">
            <li>账户资金固定，不追加、不提取。</li>
            <li>
              下单直接由交易系统执行：不符合 A 股规则或超出可用资金的委托会被系统拒绝并返回原因，
              AI 根据返回结果自行调整，就像用券商软件下单一样。
            </li>
          </ul>
          <p class="hard__note">这些限制写在交易系统里，不写进 AI 提示词；风格与仓位完全由 AI 自定。</p>
        </div>
        <div class="form__foot">
          <button class="ui-btn" @click="settingsOpen = false">取消</button>
          <button class="ui-btn ui-btn--primary" :disabled="saving" @click="saveSettings">{{ saving ? '保存中…' : '保存' }}</button>
        </div>
      </div>
    </Drawer>
  </div>
</template>

<style scoped>
.kv { display: flex; gap: 10px; font-size: var(--fs-sm); }
.kv__k { color: var(--text-faint); }
.kv__v { font-weight: 600; }
.trader { display: flex; flex-direction: column; gap: var(--sp-4); }
/* .metrics 已收敛到全局样式（styles/base.css） */

.bar {
  display: flex; align-items: center; justify-content: space-between; gap: var(--sp-3);
  flex-wrap: wrap;
  padding: var(--sp-3) var(--sp-4);
  background: var(--panel-2); border: 1px solid var(--border); border-radius: var(--radius-md);
}
.bar__meta { display: flex; align-items: center; gap: 8px; font-size: var(--fs-sm); color: var(--text-sub); flex-wrap: wrap; }
.bar__actions { display: flex; gap: var(--sp-2); }
.sep { color: var(--text-faint); }
.dot { width: 8px; height: 8px; border-radius: 50%; background: var(--text-faint); }
.dot--ok { background: var(--ok); }
.dot--off { background: var(--text-faint); }

.progress { display: flex; flex-direction: column; gap: 6px; }
.progress__bar { height: 4px; border-radius: 999px; background: var(--panel-2); overflow: hidden; }
.progress__fill { height: 100%; background: var(--accent); transition: width 0.3s ease; }
.progress__msg { font-size: var(--fs-xs); color: var(--text-faint); }

.decision { display: flex; flex-direction: column; gap: var(--sp-4); }
.decision__row { display: flex; align-items: center; gap: var(--sp-3); flex-wrap: wrap; }
.block { display: flex; flex-direction: column; gap: 8px; }
.block__title { font-size: var(--fs-sm); font-weight: 600; color: var(--text-sub); }
.prose { font-size: var(--fs-md); line-height: 1.75; color: var(--text); white-space: pre-wrap; margin: 0; }
.prose--sub { color: var(--text-sub); font-size: var(--fs-sm); }
.muted { color: var(--text-faint); font-size: var(--fs-xs); }
.up { color: var(--up); }
.down { color: var(--down); }
.ok { color: var(--ok); }
.bad { color: var(--up); }
.navchg { font-size: var(--fs-sm); font-weight: 600; }

.tag { font-size: var(--fs-xs); padding: 2px 8px; border-radius: 999px; font-weight: 600; }
.tag--act { background: color-mix(in srgb, var(--accent) 16%, transparent); color: var(--accent); }
.tag--hold { background: var(--panel-2); color: var(--text-sub); }
.tag--sm { font-size: 11px; }

.alert { padding: 8px 12px; border-radius: var(--radius-sm); background: color-mix(in srgb, var(--up) 12%, transparent); color: var(--up); font-size: var(--fs-sm); }

.mini { width: 100%; border-collapse: collapse; font-size: var(--fs-sm); }
.mini th { text-align: left; color: var(--text-faint); font-weight: 500; padding: 6px 8px; border-bottom: 1px solid var(--border); }
.mini td { padding: 8px; border-bottom: 1px solid var(--border); }
.ta-r { text-align: right; }

.collapse { display: inline-flex; align-items: center; gap: 6px; background: none; border: none; color: var(--text-sub); font-size: var(--fs-sm); cursor: pointer; padding: 0; }
.news { display: flex; flex-direction: column; gap: var(--sp-3); margin-top: 6px; }
.news__group { display: flex; flex-direction: column; gap: 4px; }
.news__label { font-size: var(--fs-xs); color: var(--accent); font-weight: 600; }
.news__item { display: flex; gap: 8px; font-size: var(--fs-sm); line-height: 1.5; }
.news__item a { color: var(--text); text-decoration: none; }
.news__item a:hover { color: var(--accent); }
.news__time { color: var(--text-faint); font-size: var(--fs-xs); flex: none; width: 78px; }

.timeline { display: flex; flex-direction: column; }
.tl-item { border-bottom: 1px solid var(--border); }
.tl-item:last-child { border-bottom: none; }
.tl-head { display: flex; align-items: center; gap: var(--sp-3); padding: var(--sp-3) var(--sp-4); cursor: pointer; }
.tl-head:hover { background: var(--panel-2); }
.tl-date { font-variant-numeric: tabular-nums; font-size: var(--fs-sm); color: var(--text-sub); flex: none; width: 92px; }
.tl-nav { font-size: var(--fs-xs); font-weight: 600; }
.tl-status { font-size: var(--fs-xs); color: var(--text-faint); margin-left: auto; }
.tl-status.error { color: var(--up); }
.tl-chev { color: var(--text-faint); flex: none; }
.tl-body { padding: 0 var(--sp-4) var(--sp-4) calc(92px + var(--sp-3) + var(--sp-4)); display: flex; flex-direction: column; gap: 6px; }

.trace { display: flex; flex-direction: column; gap: 4px; margin-top: 6px; }
.trace__item { display: flex; gap: 8px; font-size: var(--fs-xs); color: var(--text-sub); line-height: 1.6; }
.trace__item.is-err { color: var(--up); }
.trace__idx { flex: none; width: 18px; color: var(--text-faint); text-align: right; }

.mem { display: flex; flex-direction: column; gap: var(--sp-2); }.mem__item { padding: var(--sp-3); border: 1px solid var(--border); border-radius: var(--radius-sm); background: var(--panel-2); }
.mem__item.is-off { opacity: 0.5; }
.mem__head { display: flex; align-items: center; gap: var(--sp-3); margin-bottom: 6px; }
.mem__code { font-size: var(--fs-xs); font-weight: 600; color: var(--accent); }
.mem__time { font-size: var(--fs-xs); color: var(--text-faint); }
.mem__toggle { margin-left: auto; background: none; border: none; color: var(--text-faint); font-size: var(--fs-xs); cursor: pointer; }
.mem__toggle:hover { color: var(--accent); }
.mem__body { margin: 0; font-size: var(--fs-sm); line-height: 1.6; color: var(--text); }

.seg { display: inline-flex; border: 1px solid var(--border); border-radius: var(--radius-sm); overflow: hidden; }
.seg__btn { background: none; border: none; padding: 4px 12px; font-size: var(--fs-xs); color: var(--text-sub); cursor: pointer; }
.seg__btn.is-on { background: var(--panel-2); color: var(--accent); font-weight: 600; }

.form { display: flex; flex-direction: column; gap: var(--sp-4); }
.form__grid { display: grid; grid-template-columns: 1fr 1fr; gap: var(--sp-3); }
.form__foot { display: flex; justify-content: flex-end; gap: var(--sp-2); margin-top: var(--sp-2); }
.switch { display: flex; align-items: center; gap: 8px; font-size: var(--fs-sm); color: var(--text-sub); }
textarea.ui-input { resize: vertical; font-family: inherit; }

.hard { padding: var(--sp-3); border: 1px solid var(--border); border-radius: var(--radius-sm); background: var(--panel-2); }
.hard__title { font-size: var(--fs-xs); font-weight: 600; color: var(--text-sub); margin-bottom: 8px; }
.hard__list { margin: 0; padding-left: 18px; display: flex; flex-direction: column; gap: 6px; }
.hard__list li { font-size: var(--fs-sm); line-height: 1.6; color: var(--text); }
.hard__note { margin: 10px 0 0; font-size: var(--fs-xs); color: var(--text-faint); line-height: 1.6; }

/* 记忆条目的市场环境标签（经验按环境分桶） */
.memregime {
  flex: none;
  padding: 0 6px;
  height: 18px;
  line-height: 18px;
  border-radius: var(--radius-pill);
  background: var(--gold-dim);
  color: var(--gold);
  font-size: 10px;
}
</style>
