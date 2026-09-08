<script setup lang="ts">
import { ref, watch, onBeforeUnmount } from 'vue'
import { searchStock } from '@/api'
import type { StockRef } from '@/api'
import Icon from '@/components/Icon.vue'

/**
 * 股票搜索输入：防抖查询 + 下拉结果 + 键盘上下选择。
 * 行情/交易/AI 等所有需要选股票的地方复用它。
 */
const props = withDefaults(
  defineProps<{
    modelValue?: string
    placeholder?: string
    /** 下拉最多显示条数 */
    limit?: number
    width?: string
  }>(),
  { modelValue: '', placeholder: '搜索股票 / 代码', limit: 8, width: '220px' },
)

const emit = defineEmits<{
  'update:modelValue': [v: string]
  select: [s: StockRef]
  submit: [code: string]
}>()

const q = ref(props.modelValue)
const results = ref<StockRef[]>([])
const open = ref(false)
const activeIdx = ref(-1)
let timer: ReturnType<typeof setTimeout> | null = null

watch(
  () => props.modelValue,
  (v) => { if (v !== q.value) q.value = v },
)

function onInput() {
  emit('update:modelValue', q.value)
  if (timer) clearTimeout(timer)
  const text = q.value.trim()
  if (!text) { results.value = []; open.value = false; return }
  timer = setTimeout(async () => {
    try {
      results.value = (await searchStock(text)).slice(0, props.limit)
      open.value = results.value.length > 0
      activeIdx.value = -1
    } catch {
      results.value = []
      open.value = false
    }
  }, 250)
}

function pick(s: StockRef) {
  q.value = s.code
  emit('update:modelValue', s.code)
  emit('select', s)
  open.value = false
}

function onKeydown(e: KeyboardEvent) {
  if (!open.value) {
    if (e.key === 'Enter') emit('submit', q.value.trim())
    return
  }
  if (e.key === 'ArrowDown') {
    e.preventDefault()
    activeIdx.value = Math.min(activeIdx.value + 1, results.value.length - 1)
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    activeIdx.value = Math.max(activeIdx.value - 1, 0)
  } else if (e.key === 'Enter') {
    e.preventDefault()
    if (activeIdx.value >= 0) pick(results.value[activeIdx.value])
    else emit('submit', q.value.trim())
    open.value = false
  } else if (e.key === 'Escape') {
    open.value = false
  }
}

function onBlur() {
  setTimeout(() => { open.value = false }, 150)
}

onBeforeUnmount(() => { if (timer) clearTimeout(timer) })
</script>

<template>
  <div class="search-input" :style="{ width }">
    <Icon name="search" :size="14" class="search-input__icon" />
    <input
      v-model="q"
      class="ui-input search-input__field"
      :placeholder="placeholder"
      @input="onInput"
      @keydown="onKeydown"
      @blur="onBlur"
      @focus="results.length && (open = true)"
    />
    <div v-if="open && results.length" class="search-input__pop">
      <button
        v-for="(s, i) in results"
        :key="s.code"
        class="search-input__item"
        :class="{ 'is-active': i === activeIdx }"
        @mousedown.prevent="pick(s)"
        @mouseenter="activeIdx = i"
      >
        <span class="search-input__code num">{{ s.code }}</span>
        <span class="search-input__name">{{ s.name }}</span>
        <span v-if="s.status" class="search-input__status">{{ s.status }}</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.search-input { position: relative; }
.search-input__icon {
  position: absolute;
  left: 10px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--text-faint);
  pointer-events: none;
}
.search-input__field { padding-left: 30px; }
.search-input__pop {
  position: absolute;
  z-index: 60;
  top: calc(100% + 6px);
  left: 0;
  right: 0;
  min-width: 260px;
  max-height: 300px;
  overflow-y: auto;
  padding: 4px;
  background: var(--bg-overlay);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-2);
}
.search-input__item {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  width: 100%;
  padding: 7px 10px;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text);
  font-size: var(--fs-sm);
  text-align: left;
  cursor: pointer;
}
.search-input__item.is-active { background: var(--bg-hover); }
.search-input__code { color: var(--gold); font-weight: 600; }
.search-input__name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.search-input__status { color: var(--text-faint); font-size: var(--fs-xs); }
</style>
