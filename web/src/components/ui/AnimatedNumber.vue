<script setup lang="ts">
/**
 * 数字滚动：值变化时从旧值缓动到新值（关键指标用，别滥用）。
 * - 用 requestAnimationFrame 逐帧插值，格式化交给调用方的 format
 * - 系统「减少动态效果」时直接显示终值
 */
import { onBeforeUnmount, ref, watch } from 'vue'

const props = withDefaults(
  defineProps<{
    value: number
    format?: (n: number) => string
    /** 缓动时长（毫秒） */
    duration?: number
  }>(),
  { duration: 520 },
)

const shown = ref(props.value)
let rafId = 0

function reduceMotion() {
  return window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false
}

function animate(from: number, to: number) {
  cancelAnimationFrame(rafId)
  if (reduceMotion() || !Number.isFinite(to - from) || from === to) {
    shown.value = to
    return
  }
  const t0 = performance.now()
  const step = (now: number) => {
    const p = Math.min(1, (now - t0) / props.duration)
    // easeOutCubic
    const e = 1 - Math.pow(1 - p, 3)
    shown.value = from + (to - from) * e
    if (p < 1) rafId = requestAnimationFrame(step)
    else shown.value = to
  }
  rafId = requestAnimationFrame(step)
}

watch(
  () => props.value,
  (to, from) => {
    if (typeof to !== 'number' || Number.isNaN(to)) {
      shown.value = to
      return
    }
    if (typeof from !== 'number' || Number.isNaN(from)) {
      shown.value = to
      return
    }
    animate(from, to)
  },
)

onBeforeUnmount(() => cancelAnimationFrame(rafId))

const text = () => (props.format ? props.format(shown.value) : String(Math.round(shown.value)))
</script>

<template>
  <span class="anim-num">{{ text() }}</span>
</template>

<style scoped>
.anim-num {
  font-variant-numeric: tabular-nums;
  font-family: var(--font-num);
}
</style>
