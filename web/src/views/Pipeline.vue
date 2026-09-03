<script setup lang="ts">
import { onMounted, ref, onBeforeUnmount } from 'vue'
import PageHeader from '@/components/PageHeader.vue'
import Card from '@/components/Card.vue'
import StatCard from '@/components/StatCard.vue'
import Skeleton from '@/components/Skeleton.vue'
import Icon from '@/components/Icon.vue'
import { useToastStore } from '@/stores/toast'
import { streamJob } from '@/api/client'
import { getPipelineStats, getPipelineStatus, triggerPipelineUpdate } from '@/api'
import type { PipelineStats, PipelineStatus } from '@/api'

const toast = useToastStore()
const stats = ref<PipelineStats | null>(null)
const status = ref<PipelineStatus | null>(null)
const loading = ref(true)
const updating = ref(false)
const progress = ref(0)
const progressMsg = ref('')
let closeStream: (() => void) | null = null

onMounted(async () => {
  try {
    const [s, st] = await Promise.all([getPipelineStats(), getPipelineStatus()])
    stats.value = s
    status.value = st
  } catch (e) {
    toast.error('管道状态加载失败：' + (e instanceof Error ? e.message : String(e)))
  } finally { loading.value = false }
})

onBeforeUnmount(() => closeStream?.())

async function startUpdate(poolOnly = false) {
  updating.value = true; progress.value = 0; progressMsg.value = '提交中…'
  try {
    const job = await triggerPipelineUpdate(poolOnly)
    progressMsg.value = '任务已提交，等待执行…'
    closeStream?.()
    closeStream = streamJob(job.job_id, {
      onProgress: (frame) => {
        progress.value = typeof frame.pct === 'number' ? frame.pct : Math.min(95, progress.value + 8)
        progressMsg.value = String(frame.msg || frame.message || '更新中…')
      },
      onResult: () => {
        progress.value = 100
        progressMsg.value = '更新完成'
        updating.value = false
        toast.success('数据更新完成')
        refreshStats()
      },
      onError: (m) => {
        progressMsg.value = '出错：' + m
        updating.value = false
        toast.error('更新失败：' + m)
      },
    })
  } catch (e: unknown) {
    toast.error('提交失败：' + (e instanceof Error ? e.message : String(e)))
    updating.value = false
  }
}

async function refreshStats() {
  try {
    const [s, st] = await Promise.all([getPipelineStats(), getPipelineStatus()])
    stats.value = s; status.value = st
  } catch { /* keep stale */ }
}
</script>

<template>
  <div class="pipeline">
    <PageHeader title="数据管道" subtitle="K线数据更新与状态监控">
      <template #right>
        <button class="btn" @click="refreshStats" :disabled="loading">
          <Icon name="refresh" :size="14" /> 刷新
        </button>
      </template>
    </PageHeader>

    <Skeleton v-if="loading && !stats" />

    <!-- progress bar -->
    <Card v-if="updating" class="progress-card">
      <div class="progress-hd">
        <Icon name="refresh" :size="16" class="spin" />
        <span>{{ progressMsg }}</span>
      </div>
      <div class="bar-track">
        <div class="bar-fill" :style="{ width: progress + '%' }" />
      </div>
      <div class="progress-pct num">{{ progress }}%</div>
    </Card>

    <!-- stats grid -->
    <div class="stats" v-if="stats">
      <StatCard label="股票数量" :value="String(stats.stock_count || 0)" icon="layers" />
      <StatCard label="K线总行数" :value="stats.kline_rows ? (stats.kline_rows / 1e6).toFixed(1) + 'M' : '—'" icon="datacenter" />
      <StatCard label="最新日期" :value="stats.latest_date || '—'" icon="log" />
      <StatCard label="数据库大小" :value="stats.db_size || '—'" icon="database" />
    </div>

    <!-- last update status -->
    <Card v-if="status" class="mt">
      <template #header><span class="card-title">上次更新</span></template>
      <div v-if="status.last_update" class="status-detail">
        <div class="meta-row">
          <span class="meta-k">时间</span>
          <span class="meta-v">{{ status.last_update }}</span>
        </div>
        <div class="meta-row" v-if="status.steps">
          <span class="meta-k">K线</span>
          <span class="meta-v">{{ (status.steps as Record<string,unknown>).kline as string }}</span>
        </div>
        <div class="meta-row" v-if="status.steps">
          <span class="meta-k">基本面</span>
          <span class="meta-v">{{ (status.steps as Record<string,unknown>).fundamental as string }}</span>
        </div>
      </div>
      <div v-else class="muted">尚未执行过更新</div>
    </Card>

    <!-- action buttons -->
    <div class="actions">
      <button class="btn primary" @click="startUpdate(false)" :disabled="updating">
        <Icon :name="updating ? 'refresh' : 'play'" :size="15" :class="{ spin: updating }" />
        {{ updating ? '更新中…' : '全量更新' }}
      </button>
      <button class="btn" @click="startUpdate(true)" :disabled="updating">
        <Icon name="refresh" :size="14" />
        仅更新量化池
      </button>
    </div>
  </div>
</template>

<style scoped>
.pipeline { max-width: 900px; }
.progress-card { margin-bottom: var(--sp-4); }
.progress-hd { display: flex; align-items: center; gap: var(--sp-2); margin-bottom: var(--sp-3); font-weight: 600; }
.bar-track { height: 8px; background: var(--bg); border-radius: 4px; overflow: hidden; }
.bar-fill { height: 100%; background: var(--gold); border-radius: 4px; transition: width 0.3s ease; }
.progress-pct { text-align: right; font-size: var(--fs-sm); color: var(--text-sub); margin-top: var(--sp-1); }
.stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: var(--sp-3); margin-bottom: var(--sp-4); }
.mt { margin-top: var(--sp-4); }
.card-title { font-weight: 600; font-size: var(--fs-md); }
.status-detail { display: flex; flex-direction: column; gap: var(--sp-2); }
.meta-row { display: flex; justify-content: space-between; }
.meta-k { color: var(--text-sub); font-size: var(--fs-sm); }
.meta-v { font-size: var(--fs-sm); font-family: var(--font-mono); }
.actions { display: flex; gap: var(--sp-3); margin-top: var(--sp-5); }
.btn {
  display: inline-flex; align-items: center; gap: var(--sp-2);
  padding: 9px 18px; border: 1px solid var(--border); border-radius: var(--radius-sm);
  background: var(--bg-raised); color: var(--text-sub); font-size: var(--fs-sm); cursor: pointer;
  transition: all var(--dur-fast);
}
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.btn.primary { background: var(--gold); color: var(--on-gold); border-color: var(--gold); font-weight: 600; }
.btn.primary:hover { background: var(--gold-hover); }
.muted { color: var(--text-faint); font-size: var(--fs-sm); }
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
