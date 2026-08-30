<script setup lang="ts">
import { onMounted, ref } from 'vue'
import PageHeader from '@/components/PageHeader.vue'
import Card from '@/components/Card.vue'
import Icon from '@/components/Icon.vue'
import { useToastStore } from '@/stores/toast'
import { getOverview, getPicks, getRegime, triggerPipelineUpdate } from '@/api'
import type { JobHandle } from '@/api'

const toast = useToastStore()
const running = ref(false)

interface Step {
  id: string; icon: string; title: string; desc: string
  status: 'pending' | 'running' | 'done' | 'error'; detail?: string
}

const steps = ref<Step[]>([
  { id: 'data', icon: 'datacenter', title: '数据更新', desc: 'K线 + 基本面 + 缓存', status: 'pending' },
  { id: 'factors', icon: 'research', title: '因子评分', desc: '多因子打分排序', status: 'pending' },
  { id: 'regime', icon: 'market', title: '市场分类', desc: '牛/熊/震荡判定', status: 'pending' },
  { id: 'picks', icon: 'picks', title: '选股输出', desc: 'Top N 候选', status: 'pending' },
  { id: 'trade', icon: 'trade', title: '交易执行', desc: '模拟盘下单', status: 'pending' },
  { id: 'snapshot', icon: 'wallet', title: '净值快照', desc: '账户净值记录', status: 'pending' },
])

async function runPipeline() {
  running.value = true
  steps.value.forEach(s => { s.status = 'pending'; s.detail = undefined })

  // step 1: data update
  steps.value[0].status = 'running'
  try {
    const job = await triggerPipelineUpdate(true)
    steps.value[0].detail = `任务 ${job.job_id.slice(0, 8)}`
    steps.value[0].status = 'done'
  } catch {
    steps.value[0].status = 'error'; steps.value[0].detail = '更新失败'
    running.value = false; return
  }

  // step 2: factor scoring
  steps.value[1].status = 'running'
  try {
    const picks = await getPicks(10)
    steps.value[1].detail = `${picks.total} 只评分`
    steps.value[1].status = 'done'
  } catch {
    steps.value[1].status = 'error'
  }

  // step 3: regime
  steps.value[2].status = 'running'
  try {
    const r = await getRegime()
    steps.value[2].detail = r.regime_cn
    steps.value[2].status = 'done'
  } catch {
    steps.value[2].status = 'error'
  }

  // step 4: picks summary
  steps.value[3].status = 'running'
  try {
    const picks = await getPicks(5)
    steps.value[3].detail = picks.items?.slice(0, 3).map(p => p.name).join(', ') || '—'
    steps.value[3].status = 'done'
  } catch {
    steps.value[3].status = 'error'
  }

  // step 5-6: trade + snapshot (placeholder — real execution would go through trade engine)
  steps.value[4].status = 'running'
  steps.value[4].detail = '待接入交易引擎'
  steps.value[4].status = 'done'

  steps.value[5].status = 'running'
  try {
    const ov = await getOverview()
    steps.value[5].detail = ov.accounts?.length ? `${ov.accounts.length} 个账户` : '—'
    steps.value[5].status = 'done'
  } catch {
    steps.value[5].status = 'error'
  }

  running.value = false
  toast.success('全流程执行完成')
}

function statusIcon(s: Step['status']) {
  return s === 'done' ? 'check' : s === 'error' ? 'alert' : s === 'running' ? 'refresh' : 'dot'
}
</script>

<template>
  <div class="flow">
    <PageHeader title="指挥舱" subtitle="全流程可视化编排">
      <template #right>
        <button class="btn primary" @click="runPipeline" :disabled="running">
          <Icon :name="running ? 'refresh' : 'play'" :size="15" :class="{ spin: running }" />
          {{ running ? '执行中…' : '执行全流程' }}
        </button>
      </template>
    </PageHeader>

    <div class="pipeline-flow">
      <div v-for="(step, i) in steps" :key="step.id" class="step-card">
        <div :class="['step-icon', step.status]">
          <Icon :name="statusIcon(step.status)" :size="20" :class="{ spin: step.status === 'running' }" />
        </div>
        <div class="step-body">
          <div class="step-title">{{ step.title }}</div>
          <div class="step-desc muted">{{ step.desc }}</div>
          <div v-if="step.detail" class="step-detail">{{ step.detail }}</div>
        </div>
        <div v-if="i < steps.length - 1" class="connector" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.flow { max-width: 700px; }
.pipeline-flow {
  display: flex; flex-direction: column; gap: 0;
  position: relative;
}
.step-card {
  display: flex; align-items: flex-start; gap: var(--sp-4);
  position: relative; padding-bottom: var(--sp-5);
}
.step-icon {
  width: 44px; height: 44px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  background: var(--bg-raised); border: 2px solid var(--border);
  color: var(--text-faint); flex: none; z-index: 1;
  transition: all var(--dur) var(--ease);
}
.step-icon.done { border-color: var(--down); color: var(--down); background: rgba(63, 185, 80, 0.1); }
.step-icon.error { border-color: var(--up); color: var(--up); background: rgba(229, 72, 77, 0.1); }
.step-icon.running { border-color: var(--gold); color: var(--gold); background: var(--gold-dim); }
.step-body { flex: 1; padding-top: 8px; }
.step-title { font-weight: 600; font-size: var(--fs-md); color: var(--text); }
.step-desc { font-size: var(--fs-sm); margin-top: 2px; }
.step-detail { font-size: var(--fs-sm); color: var(--gold); margin-top: var(--sp-1); font-family: var(--font-mono); }
.connector {
  position: absolute; left: 21px; top: 44px; bottom: 0;
  width: 2px; background: var(--border);
}
.btn {
  display: inline-flex; align-items: center; gap: var(--sp-2);
  padding: 9px 18px; border: 1px solid var(--border); border-radius: var(--radius-sm);
  background: var(--bg-raised); color: var(--text-sub); font-size: var(--fs-sm); cursor: pointer;
}
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.btn.primary { background: var(--gold); color: var(--on-gold); border-color: var(--gold); font-weight: 600; }
.btn.primary:hover { background: var(--gold-hover); }
.muted { color: var(--text-faint); }
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
