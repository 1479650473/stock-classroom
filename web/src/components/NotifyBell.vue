<script setup lang="ts">
/**
 * 通知铃铛 —— 任务失败 / 每日自动化异常 / 测试通知。
 * 数据来自 /api/notify/*，与后台任务抽屉互补（任务=过程，通知=异常留痕）。
 */
import { computed, onMounted, ref, watch } from 'vue'
import Icon from '@/components/Icon.vue'
import Drawer from '@/components/ui/Drawer.vue'
import { api } from '@/api/client'

interface NotifyItem {
  id: number; ts: string; kind: string; level: 'info' | 'warn' | 'error' | string
  title: string; detail?: string; read: boolean
}

const open = ref(false)
const items = ref<NotifyItem[]>([])
const unread = ref(0)
const loading = ref(false)

const levelIcon = (lv: string) => (lv === 'error' ? 'alert' : lv === 'warn' ? 'alert' : 'sparkles')
const levelClass = (lv: string) => (lv === 'error' ? 'lv--error' : lv === 'warn' ? 'lv--warn' : 'lv--info')

async function load() {
  loading.value = true
  try {
    const r = await api.get<{ items: NotifyItem[]; unread: number }>('/api/notify/list', { limit: 50 })
    items.value = r.items || []
    unread.value = r.unread || 0
  } catch { /* 后端没起时静默 */ } finally {
    loading.value = false
  }
}

async function markAll() {
  await api.post('/api/notify/read', {})
  await load()
}

async function clearAll() {
  await api.post('/api/notify/clear', {})
  await load()
}

async function markOne(it: NotifyItem) {
  if (it.read) return
  await api.post('/api/notify/read', { ids: [it.id] })
  it.read = true
  unread.value = Math.max(0, unread.value - 1)
}

watch(open, (v) => { if (v) load() })
onMounted(load)
// 每 2 分钟刷新未读数（失败的任务会持续产生通知）
// 通知轮询：默认 2 分钟；页面在后台时跳过（省电、少打扰本地服务），
// 重新可见时立刻补一次，保证回来就看到最新。
const POLL_MS = 120_000
setInterval(() => {
  if (document.visibilityState === 'visible') void load()
}, POLL_MS)
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') void load()
})
const hasAny = computed(() => items.value.length > 0)
</script>

<template>
  <button
    class="tb-btn task-btn"
    :class="{ 'has-task': unread > 0 }"
    :title="unread ? `${unread} 条未读通知` : '通知'"
    @click="open = true"
  >
    <Icon name="bell" :size="16" />
    <span v-if="unread" class="badge">{{ unread > 99 ? '99+' : unread }}</span>
  </button>

  <Drawer
    :open="open"
    title="通知"
    :desc="unread ? `${unread} 条未读 · 任务失败与数据异常会记在这里` : '没有未读通知'"
    :width="420"
    @update:open="open = $event"
  >
    <div class="nbar">
      <button class="ui-btn ui-btn--ghost" :disabled="!unread" @click="markAll">全部已读</button>
      <button class="ui-btn ui-btn--ghost" :disabled="!hasAny" @click="clearAll">清空</button>
    </div>
    <p v-if="loading && !hasAny" class="empty">加载中…</p>
    <p v-else-if="!hasAny" class="empty">暂无通知</p>
    <article v-for="it in items" :key="it.id" class="note" :class="{ 'note--unread': !it.read }"
      @click="markOne(it)">
      <div class="note__head">
        <Icon :name="levelIcon(it.level)" :size="13" :class="levelClass(it.level)" />
        <span class="note__title">{{ it.title }}</span>
        <span class="note__ts">{{ it.ts.slice(5, 16) }}</span>
      </div>
      <p v-if="it.detail" class="note__detail">{{ it.detail }}</p>
      <span class="note__kind">{{ it.kind }}</span>
    </article>
  </Drawer>
</template>

<style scoped>
.nbar { display: flex; gap: 8px; margin-bottom: 10px; }
.note { padding: 10px 12px; border-radius: var(--radius-sm); background: var(--panel-2);
  margin-bottom: 8px; cursor: pointer; border-left: 3px solid transparent; }
.note--unread { border-left-color: var(--accent); }
.note__head { display: flex; align-items: center; gap: 6px; }
.note__title { flex: 1; font-size: var(--fs-sm); font-weight: 600; color: var(--text); }
.note__ts { font-size: var(--fs-xs); color: var(--text-faint); }
.note__detail { margin: 4px 0 0; font-size: var(--fs-xs); color: var(--text-sub); line-height: 1.6;
  white-space: pre-wrap; word-break: break-all; }
.note__kind { font-size: 10px; color: var(--text-faint); }
.lv--error { color: var(--down, #ff6b6b); }
.lv--warn { color: var(--accent); }
.lv--info { color: var(--text-faint); }
.empty { font-size: var(--fs-xs); color: var(--text-faint); }
</style>
