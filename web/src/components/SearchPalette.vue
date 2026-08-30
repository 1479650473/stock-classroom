<script setup lang="ts">
import { ref, watch, nextTick, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import Icon from './Icon.vue'
import { searchStock } from '@/api'
import type { StockRef } from '@/api'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ (e: 'close'): void }>()

const router = useRouter()
const q = ref('')
const results = ref<StockRef[]>([])
const loading = ref(false)
const active = ref(0)
const inputEl = ref<HTMLInputElement>()

let timer: ReturnType<typeof setTimeout> | null = null

watch(() => props.open, async (v) => {
  if (v) {
    q.value = ''
    results.value = []
    active.value = 0
    await nextTick()
    inputEl.value?.focus()
  }
})

watch(q, (val) => {
  if (timer) clearTimeout(timer)
  if (!val.trim()) {
    results.value = []
    return
  }
  timer = setTimeout(run, 220)
})

async function run() {
  loading.value = true
  try {
    results.value = await searchStock(q.value.trim())
    active.value = 0
  } catch {
    results.value = []
  } finally {
    loading.value = false
  }
}

function pick(item: StockRef) {
  emit('close')
  router.push({ path: '/kline', query: { code: item.code, name: item.name } })
}

function onKey(e: KeyboardEvent) {
  if (e.key === 'ArrowDown') { e.preventDefault(); active.value = Math.min(active.value + 1, results.value.length - 1) }
  else if (e.key === 'ArrowUp') { e.preventDefault(); active.value = Math.max(active.value - 1, 0) }
  else if (e.key === 'Enter') { e.preventDefault(); const it = results.value[active.value]; if (it) pick(it) }
  else if (e.key === 'Escape') { emit('close') }
}

function globalKey(e: KeyboardEvent) {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault()
    emit(props.open ? 'close' : 'open' as never)
  }
}
onMounted(() => window.addEventListener('keydown', globalKey))
onBeforeUnmount(() => window.removeEventListener('keydown', globalKey))
</script>

<template>
  <transition name="fade">
    <div v-if="open" class="overlay" @click.self="emit('close')">
      <div class="palette">
        <div class="input-row">
          <Icon name="search" :size="17" class="muted" />
          <input
            ref="inputEl"
            v-model="q"
            placeholder="输入股票代码或名称…"
            @keydown="onKey"
          />
          <kbd>Esc</kbd>
        </div>
        <div class="results" v-if="q.trim()">
          <div v-if="loading" class="hint">搜索中…</div>
          <div v-else-if="!results.length" class="hint">未找到匹配的股票</div>
          <button
            v-for="(item, i) in results"
            :key="item.code"
            class="result"
            :class="{ active: i === active }"
            @mouseenter="active = i"
            @click="pick(item)"
          >
            <span class="code num">{{ item.code }}</span>
            <span class="name">{{ item.name }}</span>
            <span v-if="item.status === 'delisted'" class="tag">已退市</span>
          </button>
        </div>
        <div class="results" v-else>
          <div class="hint">支持代码 / 名称模糊搜索，回车打开 K线</div>
        </div>
      </div>
    </div>
  </transition>
</template>

<style scoped>
.overlay {
  position: fixed; inset: 0; background: rgba(0, 0, 0, 0.5);
  display: flex; align-items: flex-start; justify-content: center;
  padding-top: 12vh; z-index: 1000; backdrop-filter: blur(2px);
}
.palette {
  width: min(560px, 90vw); background: var(--bg-overlay);
  border: 1px solid var(--border-strong); border-radius: var(--radius-lg);
  box-shadow: var(--shadow-pop); overflow: hidden;
}
.input-row {
  display: flex; align-items: center; gap: var(--sp-3);
  padding: var(--sp-4); border-bottom: 1px solid var(--border);
}
.input-row input {
  flex: 1; background: transparent; border: none; outline: none;
  color: var(--text); font-size: var(--fs-lg); font-family: inherit;
}
.input-row input::placeholder { color: var(--text-faint); }
.input-row kbd {
  font-family: var(--font-mono); font-size: 10px; color: var(--text-faint);
  border: 1px solid var(--border); border-radius: 4px; padding: 1px 6px;
}
.results { max-height: 320px; overflow-y: auto; padding: var(--sp-2); }
.hint { padding: var(--sp-5); text-align: center; color: var(--text-faint); font-size: var(--fs-sm); }
.result {
  display: flex; align-items: center; gap: var(--sp-3);
  width: 100%; padding: 10px var(--sp-3); border: none; background: transparent;
  border-radius: var(--radius-sm); cursor: pointer; color: var(--text);
  font-size: var(--fs-md); text-align: left; transition: background var(--dur-fast);
}
.result.active { background: var(--sel-bg); }
.result .code { color: var(--text-sub); width: 70px; }
.result .name { flex: 1; }
.result .tag { font-size: var(--fs-xs); color: var(--text-faint); }
.fade-enter-active, .fade-leave-active { transition: opacity var(--dur-fast); }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
