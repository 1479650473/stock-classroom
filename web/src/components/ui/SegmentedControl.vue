<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import Icon from '@/components/Icon.vue'

/**
 * 分段控件：少量互斥选项的切换（周期、买卖方向、视图模式）。
 * 比下拉更直观，比一排按钮更整洁。
 */
const props = withDefaults(
  defineProps<{
    modelValue: string
    options: { value: string; label: string; icon?: string }[]
    size?: 'md' | 'sm'
    /** 等分占满宽度 */
    block?: boolean
  }>(),
  { size: 'md', block: false },
)

const emit = defineEmits<{ 'update:modelValue': [v: string] }>()

// 滑动指示器：测量激活项位置与宽度，让选中态"滑过去"而不是硬切换
const root = ref<HTMLElement | null>(null)
const ind = ref({ left: 0, width: 0 })

function measure() {
  const el = root.value
  if (!el) return
  const items = Array.from(el.querySelectorAll<HTMLElement>('.seg__item'))
  const i = props.options.findIndex((o) => o.value === props.modelValue)
  const target = items[i]
  if (!target) return
  // 首帧就已量好，无需透明度过渡（也不依赖 rAF —— 后台标签页里 rAF 不会触发）
  ind.value = { left: target.offsetLeft, width: target.offsetWidth }
}

onMounted(() => { measure(); window.addEventListener('resize', measure) })
onBeforeUnmount(() => window.removeEventListener('resize', measure))
watch(() => [props.modelValue, props.options.length, props.size], () => nextTick(measure))
watch(root, () => nextTick(measure))
</script>

<template>
  <div ref="root" class="seg" :class="[`seg--${size}`, { 'seg--block': block }]" role="tablist">
    <span
      class="seg__ind"
      :style="{ transform: `translateX(${ind.left - 3}px)`, width: `${ind.width}px` }"
      aria-hidden="true"
    />
    <button
      v-for="opt in options"
      :key="opt.value"
      class="seg__item"
      :class="{ 'is-active': modelValue === opt.value }"
      role="tab"
      :aria-selected="modelValue === opt.value"
      @click="emit('update:modelValue', opt.value)"
    >
      <Icon v-if="opt.icon" :name="opt.icon" :size="13" />
      <span>{{ opt.label }}</span>
    </button>
  </div>
</template>

<style scoped>
.seg {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 3px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-control);
  box-shadow: inset 0 1px 3px rgba(0, 0, 0, 0.14);
}
/* 滑动指示器 */
.seg__ind {
  position: absolute;
  top: 3px;
  left: 0;
  height: calc(100% - 6px);
  border-radius: 6px;
  background: linear-gradient(180deg, var(--bg-overlay), var(--bg-raised));
  border: 1px solid var(--border-strong);
  box-shadow: inset 0 1px 0 var(--sheen), var(--shadow-1);
  transition: transform var(--dur) var(--ease-out), width var(--dur) var(--ease-out);
}
.seg--block { display: flex; width: 100%; }
.seg--block .seg__item { flex: 1; }
.seg__item {
  position: relative;
  z-index: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  height: 26px;
  padding: 0 12px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--text-sub);
  font-size: var(--fs-sm);
  font-weight: 500;
  white-space: nowrap;
  cursor: pointer;
  transition: all var(--dur-fast) var(--ease);
}
.seg--sm .seg__item { height: 22px; padding: 0 9px; font-size: var(--fs-xs); }
.seg__item:hover { color: var(--text); }
.seg__item.is-active {
  background: transparent;
  color: var(--text);
  font-weight: 600;
}
.seg__item:focus-visible { outline: none; box-shadow: 0 0 0 3px var(--ring); border-radius: 6px; }
</style>
