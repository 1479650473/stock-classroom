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
  saveTraderProfile, runTrader,
} from '@/api'
import type { TraderState, TraderDecision, TraderMemory } from '@/api'

const toast = useToastStore()
const jobs = useJobsStore()

const state = ref<TraderState | null>(null)
const decisions = ref<TraderDecision[]>([])
const memory = ref<TraderMemory[]>([])
const loading = ref(true)
const error = ref('')
const memKind = ref<'thesis' | 'lesson' | 'note'>('thesis')
const expanded = ref<Record<string, boolean>>({})
const settingsOpen = ref(false)
const saving = ref(false)

// 设置草稿
const draft = ref({ persona: '', enabled: 1, max_positions: 8, min_cash_pct: 5, max_new_buys_per_day: 2 })

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
    const st = await getTraderState()
    state.value = st
    const rr = st.profile.risk_rules || {}
    draft.value = {
      persona: st.profile.persona || '',
      enabled: st.profile.enabled,
      max_positions: Number(rr.max_positions ?? 8),
      min_cash_pct: Number(rr.min_cash_pct ?? 5),
      max_new_buys_per_day: Number(rr.max_new_buys_per_day ?? 2),
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
}

async function loadLists() {
  try {
    const [d, m] = await Promise.all([
      getTraderDecisions(30),
      getTraderMemory(memKind.value === 'thesis' ? 'thesis' : memKind.value),
    ])
    decisions.value = d.items
    memory.value = m.items
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
    submit: () => runTrader({ force: true }),
    route: '/ai?tab=trader',
  })
}

async function saveSettings() {
  saving.value = true
  try {
    const cur = state.value?.profile.risk_rules || {}
    await saveTraderProfile({
      persona: draft.value.persona,
      enabled: draft.value.enabled,
      risk_rules: {
        ...cur,
        max_positions: Number(draft.value.max_positions),
        min_cash_pct: Number(draft.value.min_cash_pct),
        max_new_buys_per_day: Number(draft.value.max_new_buys_per_day),
      },
    })
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
function toggleExpand(key: string) {
  expanded.value[key] = !expanded.value[key]
}
function execOf(d: TraderDecision, code: string, side: string) {
  return (d.executions || []).find((e) => e.code === code && e.side === side)
}

const KIND_LABEL: Record<string, string> = { thesis: '持仓逻辑', lesson: '经验教训', note: '观察笔记' }
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

      <!-- 今日/最近决策 -->
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
            <span v-if="navDelta(latest) != null" class="navchg" :class="navDelta(latest)! >= 0 ? 'up' : 'down'">
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
                  <td class="ta-r">{{ o.price || execOf(latest, o.code, o.side)?.price || '市价' }}</td>
                  <td>
                    <span v-if="execOf(latest, o.code, o.side)?.ok" class="ok">{{ execOf(latest, o.code, o.side)?.detail }}</span>
                    <span v-else class="bad">{{ execOf(latest, o.code, o.side)?.detail || '未执行' }}</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <div v-if="latest.reflection" class="block">
            <div class="block__title">复盘</div>
            <p class="prose">{{ latest.reflection }}</p>
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
              <span v-if="navDelta(d) != null" class="tl-nav" :class="navDelta(d)! >= 0 ? 'up' : 'down'">
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
              v-for="k in (['thesis', 'lesson', 'note'] as const)"
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
              <span class="mem__time">{{ m.created_at }}</span>
              <button class="mem__toggle" @click="toggleMem(m)">{{ m.active ? '停用' : '恢复' }}</button>
            </div>
            <p class="mem__body">{{ m.content }}</p>
          </div>
        </div>
      </SectionCard>
    </template>

    <!-- 设置抽屉 -->
    <Drawer :open="settingsOpen" title="操盘手设置" desc="人设与风险约束会影响每次决策" :width="440" @update:open="settingsOpen = $event">
      <div class="form">
        <FormField label="操盘手人设">
          <textarea v-model="draft.persona" class="ui-input" rows="5" placeholder="描述交易风格与偏好" />
        </FormField>
        <FormField label="自动决策">
          <label class="switch">
            <input v-model="draft.enabled" type="checkbox" :true-value="1" :false-value="0" />
            <span>每日数据更新后自动跑一次决策（并自动下单）</span>
          </label>
        </FormField>
        <div class="form__grid">
          <FormField label="最大持仓只数">
            <input v-model.number="draft.max_positions" class="ui-input" type="number" min="1" max="30" />
          </FormField>
          <FormField label="现金下限 %">
            <input v-model.number="draft.min_cash_pct" class="ui-input" type="number" min="0" max="90" />
          </FormField>
          <FormField label="单日最多新开仓">
            <input v-model.number="draft.max_new_buys_per_day" class="ui-input" type="number" min="0" max="10" />
          </FormField>
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
.trader { display: flex; flex-direction: column; gap: var(--sp-4); }
.metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: var(--sp-3); }

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

.mem { display: flex; flex-direction: column; gap: var(--sp-2); }
.mem__item { padding: var(--sp-3); border: 1px solid var(--border); border-radius: var(--radius-sm); background: var(--panel-2); }
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
</style>
