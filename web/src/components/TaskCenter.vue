<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import Drawer from '@/components/ui/Drawer.vue'
import Icon from '@/components/Icon.vue'
import { useJobsStore, type JobRecord } from '@/stores/jobs'

const jobs = useJobsStore()
const router = useRouter()

const running = computed(() => jobs.running)
const finished = computed(() => jobs.finished)

const STATUS_TEXT: Record<string, string> = {
  queued: '排队中',
  running: '执行中',
  succeeded: '已完成',
  failed: '失败',
  cancelled: '已取消',
}

function statusTone(s: string): 'ok' | 'bad' | 'muted' | 'live' {
  if (s === 'succeeded') return 'ok'
  if (s === 'failed') return 'bad'
  if (s === 'cancelled') return 'muted'
  return 'live'
}

function timeAgo(ts?: number): string {
  if (!ts) return ''
  const d = Math.floor((Date.now() - ts) / 1000)
  if (d < 60) return `${Math.max(d, 0)} 秒前`
  if (d < 3600) return `${Math.floor(d / 60)} 分钟前`
  if (d < 86400) return `${Math.floor(d / 3600)} 小时前`
  return `${Math.floor(d / 86400)} 天前`
}

function openDetail(rec: JobRecord) {
  if (!rec.route) return
  jobs.drawerOpen = false
  router.push(rec.route)
}
</script>

<template>
  <button
    class="tb-btn task-btn"
    :class="{ 'has-task': jobs.activeCount > 0 }"
    :title="jobs.activeCount ? `${jobs.activeCount} 个任务在后台运行` : '后台任务'"
    @click="jobs.drawerOpen = true"
  >
    <Icon name="activity" :size="16" :class="{ pulse: jobs.activeCount > 0 }" />
    <span v-if="jobs.activeCount" class="badge">{{ jobs.activeCount }}</span>
  </button>

  <Drawer
    :open="jobs.drawerOpen"
    title="后台任务"
    :desc="running.length ? `${running.length} 个任务正在运行，切换页面不会中断` : '任务在后台持续运行，切换页面不会中断'"
    :width="420"
    @update:open="jobs.drawerOpen = $event"
  >
    <!-- 运行中 -->
    <section class="grp">
      <h4 class="grp__title">
        运行中
        <span class="grp__count">{{ running.length }}</span>
      </h4>
      <p v-if="!running.length" class="empty">当前没有运行中的任务</p>
      <article v-for="rec in running" :key="rec.id" class="job">
        <div class="job__hd">
          <Icon name="refresh" :size="14" class="spin" />
          <span class="job__title">{{ rec.title }}</span>
          <span class="job__pct mono">{{ rec.pct }}%</span>
        </div>
        <div class="bar"><div class="bar__fill" :style="{ width: rec.pct + '%' }" /></div>
        <div class="job__ft">
          <span class="job__msg">{{ rec.msg }}</span>
          <span class="job__time faint">{{ timeAgo(rec.startedAt) }}</span>
        </div>
        <div class="job__act">
          <button class="ui-btn ui-btn--sm ui-btn--ghost" @click="openDetail(rec)" :disabled="!rec.route">
            <Icon name="arrow-up-right" :size="13" />查看页面
          </button>
          <button class="ui-btn ui-btn--sm ui-btn--ghost" @click="jobs.cancel(rec.id)">
            <Icon name="stop" :size="13" />取消
          </button>
        </div>
      </article>
    </section>

    <!-- 最近完成 -->
    <section class="grp">
      <h4 class="grp__title">
        最近完成
        <button v-if="finished.length" class="link" @click="jobs.clearFinished()">清除记录</button>
      </h4>
      <p v-if="!finished.length" class="empty">还没有已完成的任务</p>
      <article v-for="rec in finished" :key="rec.id" class="job job--done">
        <div class="job__hd">
          <Icon
            :name="rec.status === 'succeeded' ? 'check' : rec.status === 'cancelled' ? 'stop' : 'alert'"
            :size="14"
            :class="'tone-' + statusTone(rec.status)"
          />
          <span class="job__title">{{ rec.title }}</span>
          <span class="job__state" :class="'tone-' + statusTone(rec.status)">
            {{ STATUS_TEXT[rec.status] || rec.status }}
          </span>
        </div>
        <div class="job__ft">
          <span class="job__msg" :class="{ 'tone-bad': rec.status === 'failed' }">{{ rec.msg }}</span>
          <span class="job__time faint">{{ timeAgo(rec.finishedAt) }}</span>
        </div>
        <div class="job__act" v-if="rec.route">
          <button class="ui-btn ui-btn--sm ui-btn--ghost" @click="openDetail(rec)">
            <Icon name="arrow-up-right" :size="13" />查看结果
          </button>
        </div>
      </article>
    </section>
  </Drawer>
</template>

<style scoped>
.task-btn { position: relative; }
.task-btn.has-task { color: var(--gold); }
.badge {
  position: absolute;
  top: 2px;
  right: 2px;
  min-width: 15px;
  height: 15px;
  padding: 0 4px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-pill);
  background: var(--gold);
  color: var(--on-gold);
  font-size: 10px;
  font-weight: 700;
  line-height: 1;
}
.pulse { animation: pulse 1.6s ease-in-out infinite; }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.45; } }
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

.grp { margin-bottom: var(--sp-6); }
.grp:last-child { margin-bottom: 0; }
.grp__title {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  margin: 0 0 var(--sp-3);
  font-size: var(--fs-sm);
  font-weight: 600;
  color: var(--text-sub);
}
.grp__count {
  padding: 0 6px;
  border-radius: var(--radius-pill);
  background: var(--bg-raised);
  font-size: var(--fs-xs);
  color: var(--text-faint);
}
.link {
  margin-left: auto;
  background: none;
  border: none;
  color: var(--text-faint);
  font-size: var(--fs-xs);
  cursor: pointer;
}
.link:hover { color: var(--text-sub); }
.empty { margin: 0; padding: var(--sp-4) 0; font-size: var(--fs-sm); color: var(--text-faint); }

.job {
  padding: var(--sp-3);
  margin-bottom: var(--sp-2);
  background: var(--bg-raised);
  border: 1px solid var(--border-soft);
  border-radius: var(--radius-md);
}
.job--done { background: var(--bg); }
.job__hd { display: flex; align-items: center; gap: var(--sp-2); }
.job__title { flex: 1; font-size: var(--fs-sm); font-weight: 600; color: var(--text); }
.job__pct { font-size: var(--fs-xs); color: var(--gold); }
.job__state { font-size: var(--fs-xs); font-weight: 600; }
.bar { height: 5px; margin: var(--sp-2) 0; background: var(--bg-panel); border-radius: 3px; overflow: hidden; }
.bar__fill {
  height: 100%;
  border-radius: 3px;
  background: linear-gradient(90deg, color-mix(in srgb, var(--gold) 55%, transparent), var(--gold));
  box-shadow: 0 0 10px color-mix(in srgb, var(--gold) 45%, transparent);
  transition: width var(--dur) var(--ease-out);
}
.job__ft { display: flex; align-items: center; justify-content: space-between; gap: var(--sp-2); margin-top: var(--sp-1); }
.job__msg { font-size: var(--fs-xs); color: var(--text-sub); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.job__time { font-size: var(--fs-xs); flex: none; }
.job__act { display: flex; gap: var(--sp-2); margin-top: var(--sp-2); }
.tone-ok { color: var(--ok); }
.tone-bad { color: var(--up); }
.tone-muted { color: var(--text-faint); }
.tone-live { color: var(--gold); }
</style>
