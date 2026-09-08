<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import type { Ref } from 'vue'

// 嵌入模式: 隐藏页面标题, 只保留操作区(供策略页 Tab 内嵌)
withDefaults(defineProps<{ embedded?: boolean }>(), { embedded: false })
import PageHeader from '@/components/PageHeader.vue'
import Card from '@/components/Card.vue'
import StatCard from '@/components/StatCard.vue'
import EmptyState from '@/components/EmptyState.vue'
import Skeleton from '@/components/Skeleton.vue'
import Icon from '@/components/Icon.vue'
import { useToastStore } from '@/stores/toast'
import { useJobsStore } from '@/stores/jobs'
import { api } from '@/api/client'
import { getStrategies } from '@/api'
import {
  optimizeFamilies, optimizePropose, optimizeBacktest, optimizeVerdict, optimizeAll,
  type StrategyDef, type OptimizeProposal,
} from '@/api'

const toast = useToastStore()
const jobs = useJobsStore()
const strategies = ref<StrategyDef[]>([])
const hp = ref(20)
const useLlm = ref(true)
const running = ref(false)
const progressMsg = ref('')
const progress = ref(0)

type StageState = { status: 'idle' | 'running' | 'done' | 'error'; detail?: string }
const stage1 = ref<StageState>({ status: 'idle' })
const stage2 = ref<StageState>({ status: 'idle' })
const stage3 = ref<StageState>({ status: 'idle' })
const stage4 = ref<StageState>({ status: 'idle' })

const families = ref<Record<string, { metrics: Record<string, number>; describe: { summary: string }; factors: string[]; total_return?: number }> | null>(null)
const best = ref('')
const proposal = ref<OptimizeProposal | null>(null)
const newMetrics = ref<Record<string, number> | null>(null)
const newDescribe = ref<string>('')
const verdict = ref<'accept' | 'reject' | null>(null)
const written = ref(false)

onMounted(async () => {
  try { strategies.value = await getStrategies() } catch { /* ignore */ }
  // 切回页面时，若进化任务仍在后台跑，恢复运行态显示
  const active = jobs.activeByKind('optimize')
  if (active) {
    running.value = true
    progress.value = active.pct
    progressMsg.value = active.msg
  }
})

// 任务由 jobs store 在后台持有，组件卸载不再断开；这里只同步进度显示
watch(
  () => jobs.activeByKind('optimize'),
  (j) => {
    if (j) {
      running.value = true
      progress.value = j.pct
      progressMsg.value = j.msg
    } else if (running.value) {
      running.value = false
    }
  },
)

async function waitJob(job: { job_id: string }): Promise<Record<string, unknown>> {
  const r = await jobs.waitDone(job.job_id)
  if (!r.ok) throw new Error(r.error || '任务失败')
  return (r.result || {}) as Record<string, unknown>
}

function setStage(s: Ref<StageState>, st: StageState['status'], detail?: string) {
  s.value.status = st
  if (detail !== undefined) s.value.detail = detail
}

const rows = (m: Record<string, number>) => [
  { label: '总收益', v: m.total_return },
  { label: '年化', v: m.cagr },
  { label: '夏普', v: m.sharpe },
  { label: '最大回撤', v: m.max_drawdown },
  { label: '胜率', v: m.win_rate },
  { label: '交易数', v: m.num_trades },
]
const fmtV = (v: unknown, isPct = /总收益|年化|最大回撤|胜率/.test('')): string => {
  if (typeof v !== 'number') return '—'
  if (isPct) return (v >= 0 ? '+' : '') + (v * 100).toFixed(2) + '%'
  return v.toFixed(2)
}
const fmtPct = (v: unknown) => (typeof v !== 'number' ? '—' : ((v * 100).toFixed(2)) + '%')
const fmtSign = (v: unknown) => (typeof v !== 'number' ? '—' : (v >= 0 ? '+' : '') + (v * 100).toFixed(2) + '%')

async function runAll() {
  if (running.value) return
  running.value = true
  progress.value = 0
  progressMsg.value = '提交自主进化任务…'
  setStage(stage1, 'running', '5家族回测(可能读缓存)')
  try {
    const job = await optimizeAll({ hp: hp.value, use_llm: useLlm.value, write: false, account_id: null })
    const res = await waitJob(job as unknown as { job_id: string })
    families.value = (res.families as typeof families.value) || null
    setStage(stage1, 'done', `${Object.keys((res.families as Record<string, unknown>) || {}).length} 个家族`)
    if (res.best) {
      best.value = String(res.best)
      setStage(stage2, 'done', String(res.verdict === 'accept' ? '接受' : '拒绝'))
      setStage(stage3, 'done', '契约回测完成')
      setStage(stage4, 'done', String(res.verdict))
      verdict.value = (res.verdict as 'accept' | 'reject') || null
      const nb = res.new_backtest as Record<string, unknown> | null
      newMetrics.value = (nb?.metrics as Record<string, number>) || null
      newDescribe.value = String((nb?.describe as Record<string, { summary?: string }> | undefined)?.summary || '')
      const pp = res.proposal as { name?: string } | null
      if (pp?.name) proposal.value = { ...(res.proposal as unknown as OptimizeProposal) }
      toast.success(res.verdict === 'accept' ? '进化闭环完成：接受新策略' : '进化闭环完成：新策略被拒绝')
    } else {
      setStage(stage1, 'done'); setStage(stage2, 'error'); setStage(stage3, 'error'); setStage(stage4, 'error')
    }
  } catch (e) {
    setStage(stage1, 'error', e instanceof Error ? e.message : '失败')
    toast.error('自主进化失败：' + (e instanceof Error ? e.message : String(e)))
  } finally {
    running.value = false
  }
}

async function runStage1() {
  if (running.value) return
  running.value = true
  progress.value = 0
  setStage(stage1, 'running')
  try {
    const job = await optimizeFamilies(hp.value)
    const res = await waitJob(job as unknown as { job_id: string })
    families.value = (res.families as typeof families.value) || null
    setStage(stage1, 'done', `命中缓存=${res.cached ? '是' : '否'}, as_of=${res.as_of || '?'}`)
  } catch (e) {
    setStage(stage1, 'error', e instanceof Error ? e.message : '失败')
  } finally { running.value = false }
}

async function runStage2() {
  if (running.value) return
  running.value = true
  progress.value = 0
  setStage(stage2, 'running')
  try {
    const job = await optimizePropose(hp.value, useLlm.value)
    const res = await waitJob(job as unknown as { job_id: string })
    proposal.value = res as unknown as OptimizeProposal
    setStage(stage2, 'done', proposal.value.name)
  } catch (e) {
    setStage(stage2, 'error', e instanceof Error ? e.message : '失败')
  } finally { running.value = false }
}

async function runStage3() {
  if (running.value || !proposal.value) return
  running.value = true
  progress.value = 0
  setStage(stage3, 'running')
  try {
    const job = await optimizeBacktest(hp.value, proposal.value)
    const res = await waitJob(job as unknown as { job_id: string })
    newMetrics.value = (res.metrics as Record<string, number>) || null
    newDescribe.value = String((res.describe as Record<string, { summary?: string }>)?.summary || '')
    setStage(stage3, 'done', '指标已出')
  } catch (e) {
    setStage(stage3, 'error', e instanceof Error ? e.message : '失败')
  } finally { running.value = false }
}

async function runStage4(write: boolean) {
  if (running.value || !proposal.value) return
  running.value = true
  progress.value = 0
  setStage(stage4, 'running', write ? '写入中…' : '裁决中…')
  try {
    const job = await optimizeVerdict({
      hp: hp.value, proposal: proposal.value,
      new_backtest: newMetrics.value ? { metrics: newMetrics.value } : null,
      families: {}, write,
    })
    const res = await waitJob(job as unknown as { job_id: string })
    verdict.value = (res.verdict as 'accept' | 'reject') || null
    written.value = write && !!res.new_strategy
    setStage(stage4, 'done', verdict.value === 'accept' ? '✅ 接受' : '❌ 拒绝' + (write ? '(已写入)' : ''))
    toast.success(verdict.value === 'accept' ? '新策略胜出！' : '新策略已被拒绝')
  } catch (e) {
    setStage(stage4, 'error', e instanceof Error ? e.message : '失败')
  } finally { running.value = false }
}

function reset() {
  stage1.value = { status: 'idle' }; stage2.value = { status: 'idle' }
  stage3.value = { status: 'idle' }; stage4.value = { status: 'idle' }
  families.value = null; proposal.value = null; newMetrics.value = null
  verdict.value = null; written.value = false
}

function fmtW(v: number) { return v === 1.0 ? '1.0' : v.toFixed(2) }
</script>

<template>
  <div class="optimize">
    <PageHeader title="策略进化" subtitle="AI 提案 → 回测 → 裁决 → 模拟盘（自主迭代）" :embedded="embedded">
      <template #right>
        <select v-model="hp" class="sel" title="持有期">
          <option :value="10">10 bar</option>
          <option :value="20">20 bar</option>
          <option :value="40">40 bar</option>
        </select>
        <label class="llm-toggle">
          <input v-model="useLlm" type="checkbox" /> LLM 提案
        </label>
        <button class="btn primary" @click="runAll" :disabled="running">
          <Icon :name="running ? 'refresh' : 'trending'" :size="15" :class="{ spin: running }" />
          {{ running ? '进化中…' : '一键自主进化' }}
        </button>
      </template>
    </PageHeader>

    <!-- 进度条 -->
    <Card v-if="running" class="progress-card">
      <div class="progress-hd"><Icon name="refresh" :size="15" class="spin" /> {{ progressMsg || '运行中…' }}</div>
      <div class="bar-track"><div class="bar-fill" :style="{ width: progress + '%' }" /></div>
    </Card>

    <!-- 四阶段 -->
    <div class="stages">
      <Card class="stage" :class="{ active: stage1.status !== 'idle' }">
        <div class="stage-hd">
          <Icon :name="stage1.status === 'done' ? 'check' : stage1.status === 'error' ? 'alert' : 'research'" :size="16"
            :class="stage1.status" />
          <span class="stage-title">① 5 家族回测</span>
          <button v-if="stage1.status !== 'running'" class="mini" @click="runStage1" :disabled="running">重跑</button>
        </div>
        <div class="stage-detail" v-if="stage1.detail">{{ stage1.detail }}</div>
        <div class="tbl-wrap" v-if="families">
          <table class="tbl">
            <thead><tr><th>策略</th><th class="ar">收益</th><th class="ar">年化</th><th class="ar">夏普</th><th class="ar">回撤</th></tr></thead>
            <tbody>
              <tr v-for="(f, n) in families" :key="n" :class="{ best: n === best }">
                <td>{{ n }}{{ n === best ? ' ★' : '' }}</td>
                <td class="ar num" :class="(f.total_return ?? 0) >= 0 ? 'up' : 'down'">{{ fmtSign(f.total_return) }}</td>
                <td class="ar num">{{ fmtSign(f.metrics.cagr) }}</td>
                <td class="ar num">{{ f.metrics.sharpe?.toFixed(2) ?? '—' }}</td>
                <td class="ar num down">{{ fmtPct(Math.abs(f.metrics.max_drawdown ?? 0)) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <Skeleton v-else-if="stage1.status === 'running'" />
      </Card>

      <Card class="stage" :class="{ active: stage2.status !== 'idle' }">
        <div class="stage-hd">
          <Icon :name="stage2.status === 'done' ? 'check' : stage2.status === 'error' ? 'alert' : 'agentops'" :size="16"
            :class="stage2.status" />
          <span class="stage-title">② AI 提案</span>
          <button v-if="stage2.status !== 'running'" class="mini" @click="runStage2" :disabled="running">重新提案</button>
        </div>
        <div class="stage-detail" v-if="stage2.detail">{{ stage2.detail }}</div>
        <template v-if="proposal">
          <div class="prop-name">{{ proposal.name }}</div>
          <div class="prop-desc muted">{{ proposal.description || proposal.reason }}</div>
          <div class="prop-args">
            <span v-for="f in proposal.factors" :key="f" class="factor-tag num">
              {{ f }}×{{ proposal.base_weights[f]?.toFixed(2) }}
            </span>
            <span class="muted">top_k {{ (proposal.top_k_pct * 100).toFixed(0) }}% · {{ proposal.rebalance_bars }} bar</span>
          </div>
        </template>
      </Card>

      <Card class="stage" :class="{ active: stage3.status !== 'idle' }">
        <div class="stage-hd">
          <Icon :name="stage3.status === 'done' ? 'check' : stage3.status === 'error' ? 'alert' : 'backtest'" :size="16"
            :class="stage3.status" />
          <span class="stage-title">③ 回测新契约</span>
          <button v-if="stage3.status !== 'running' && proposal" class="mini" @click="runStage3" :disabled="running">回测</button>
        </div>
        <div class="stage-detail" v-if="stage3.detail">{{ stage3.detail }}</div>
        <div class="metrics" v-if="newMetrics">
          <StatCard v-for="r in rows(newMetrics)" :key="r.label" :label="r.label"
            :value="r.label === '交易数' ? String(r.v ?? '—') : fmtSign(r.v)"
            :trend="r.label === '最大回撤' ? 'down' : ((r.v ?? 0) >= 0 ? 'up' : 'down')" />
        </div>
        <div v-if="newDescribe" class="new-desc muted">{{ newDescribe }}</div>
      </Card>

      <Card class="stage" :class="{ active: stage4.status !== 'idle' }">
        <div class="stage-hd">
          <Icon :name="stage4.status === 'done' ? 'check' : stage4.status === 'error' ? 'alert' : 'compare'" :size="16"
            :class="stage4.status" />
          <span class="stage-title">④ 裁决</span>
          <template v-if="stage4.status !== 'running' && proposal">
            <button class="mini" @click="runStage4(false)" :disabled="running">裁决</button>
            <button class="mini gold" v-if="verdict === 'accept' && !written" @click="runStage4(true)" :disabled="running">写入模拟盘</button>
          </template>
        </div>
        <div class="stage-detail" v-if="verdict">
          <span :class="['verdict-badge', verdict]">{{ verdict === 'accept' ? '✅ 接受' : '❌ 拒绝' }}</span>
          <span class="verdict-note">{{ written ? '（已写入 AI 账户）' : '' }}</span>
        </div>
        <EmptyState v-if="!verdict && !running" message="等待裁决或点击「一键自主进化」" />
      </Card>
    </div>

    <div class="actions">
      <button class="mini ghost" @click="reset">重置</button>
    </div>
  </div>
</template>

<style scoped>
.optimize { max-width: 1060px; }
.sel {
  background: var(--bg); border: 1px solid var(--border); border-radius: var(--radius-sm);
  padding: 7px 10px; color: var(--text); font-size: var(--fs-sm);
}
.llm-toggle { display: inline-flex; align-items: center; gap: 5px; font-size: var(--fs-sm); color: var(--text-sub); }
.btn {
  display: inline-flex; align-items: center; gap: var(--sp-2);
  padding: 9px 18px; border: 1px solid var(--border); border-radius: var(--radius-sm);
  background: var(--bg-raised); color: var(--text-sub); font-size: var(--fs-sm); cursor: pointer;
}
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.btn.primary { background: var(--gold); color: var(--on-gold); border-color: var(--gold); font-weight: 600; }
.btn.primary:hover { background: var(--gold-hover); }
.progress-card { margin-bottom: var(--sp-4); }
.progress-hd { display: flex; align-items: center; gap: var(--sp-2); font-size: var(--fs-sm); margin-bottom: var(--sp-2); }
.bar-track { height: 6px; background: var(--bg); border-radius: var(--radius-pill); overflow: hidden; }
.bar-fill { height: 100%; background: var(--gold); transition: width 0.3s var(--ease); }
.stages { display: flex; flex-direction: column; gap: var(--sp-3); }
.stage { padding: var(--sp-4); }
.stage.active { border-color: var(--gold); }
.stage-hd { display: flex; align-items: center; gap: var(--sp-2); margin-bottom: var(--sp-2); }
.stage-hd .check { color: var(--down); } .stage-hd .alert { color: var(--up); } .stage-hd .running, .spin { animation: spin 1s linear infinite; color: var(--gold); }
.stage-title { font-weight: 700; font-size: var(--fs-md); flex: 1; }
.mini {
  padding: 3px 10px; border: 1px solid var(--border); border-radius: var(--radius-sm);
  background: transparent; color: var(--text-sub); font-size: var(--fs-xs); cursor: pointer;
}
.mini:hover { border-color: var(--gold); color: var(--gold); }
.mini.gold { border-color: var(--gold); color: var(--gold); }
.mini.ghost { border: none; color: var(--text-faint); }
.stage-detail { font-size: var(--fs-sm); color: var(--gold); font-family: var(--font-mono); margin-bottom: var(--sp-2); }
.tbl-wrap { overflow-x: auto; }
.tbl { width: 100%; border-collapse: collapse; font-size: var(--fs-sm); }
.tbl th { padding: 8px var(--sp-2); text-align: left; color: var(--text-sub); border-bottom: 1px solid var(--border); }
.tbl .ar { text-align: right; }
.tbl td { padding: 7px var(--sp-2); border-bottom: 1px solid var(--border-soft); }
.tbl tr.best td { background: var(--gold-dim); }
.prop-name { font-weight: 700; }
.prop-desc { font-size: var(--fs-sm); margin: 4px 0 8px; }
.prop-args { display: flex; gap: var(--sp-2); flex-wrap: wrap; align-items: center; }
.factor-tag { font-size: var(--fs-xs); border: 1px solid var(--border); padding: 2px 8px; border-radius: var(--radius-pill); }
.metrics { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: var(--sp-2); margin-top: var(--sp-2); }
.new-desc { font-size: var(--fs-sm); margin-top: var(--sp-2); }
.verdict-badge { font-weight: 800; padding: 3px 12px; border-radius: var(--radius-pill); }
.verdict-badge.accept { background: rgba(63, 185, 80, 0.15); color: var(--down); }
.verdict-badge.reject { background: rgba(229, 72, 77, 0.15); color: var(--up); }
.verdict-note { font-size: var(--fs-sm); color: var(--text-sub); }
.actions { margin-top: var(--sp-4); }
.up { color: var(--up); } .down { color: var(--down); }
.muted { color: var(--text-faint); }
.num { font-family: var(--font-mono); }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
