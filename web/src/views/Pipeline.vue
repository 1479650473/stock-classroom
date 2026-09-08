<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

// 嵌入模式: 隐藏页面标题(供数据页 Tab 内嵌)
withDefaults(defineProps<{ embedded?: boolean }>(), { embedded: false })
import PageHeader from '@/components/PageHeader.vue'
import Card from '@/components/Card.vue'
import StatCard from '@/components/StatCard.vue'
import Skeleton from '@/components/Skeleton.vue'
import Icon from '@/components/Icon.vue'
import { useToastStore } from '@/stores/toast'
import { useJobsStore } from '@/stores/jobs'
import { getPipelineStats, getPipelineStatus, triggerPipelineUpdate } from '@/api'
import type { PipelineStats, PipelineStatus } from '@/api'

const toast = useToastStore()
const jobs = useJobsStore()
const stats = ref<PipelineStats | null>(null)
const status = ref<PipelineStatus | null>(null)
const loading = ref(true)

// 进度来自全局任务中心：切 Tab / 切页面 / 刷新页面都不会丢失
const job = computed(() => jobs.activeByKind('pipeline'))
const updating = computed(() => !!job.value)
const progress = computed(() => job.value?.pct ?? 0)
const progressMsg = computed(() => job.value?.msg ?? '')

onMounted(async () => {
  try {
    const [s, st] = await Promise.all([getPipelineStats(), getPipelineStatus()])
    stats.value = s
    status.value = st
  } catch (e) {
    toast.error('管道状态加载失败：' + (e instanceof Error ? e.message : String(e)))
  } finally { loading.value = false }
})

// 任务完成（成功或失败）后刷新管道状态
watch(
  () => jobs.byKind('pipeline')[0]?.doneTick ?? 0,
  (t) => { if (t) refreshStats() },
)

async function startUpdate(poolOnly = false) {
  await jobs.run({
    kind: 'pipeline',
    title: poolOnly ? '更新量化池' : '全量数据更新',
    route: '/data?tab=pipeline',
    submit: () => triggerPipelineUpdate(poolOnly),
  })
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
    <PageHeader title="数据管道" subtitle="K线数据更新与状态监控" :embedded="embedded">
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

    <!-- 更新指引 -->
    <Card class="guide">
      <template #header><span class="card-title">更新说明</span></template>
      <ol class="guide-list">
        <li>点「全量更新」拉取全市场最新交易日 K 线，约 5000 只股票，预计 3–10 分钟。</li>
        <li>更新在后台运行：可以切到其他页面继续操作，顶栏「后台任务」随时查看进度。</li>
        <li>完成后上方「最新日期」会刷新到最新交易日；若仍显示过期，请检查网络或数据源。</li>
      </ol>
      <p class="guide-tip">日常增量更新用「仅更新量化池」更快，适合盘中或盘后快速同步。</p>
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
.guide { margin-top: var(--sp-4); }
.guide-list { margin: 0; padding-left: 20px; display: flex; flex-direction: column; gap: var(--sp-2); }
.guide-list li { font-size: var(--fs-sm); color: var(--text-sub); line-height: 1.6; }
.guide-tip { margin: var(--sp-3) 0 0; font-size: var(--fs-xs); color: var(--text-faint); }
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
