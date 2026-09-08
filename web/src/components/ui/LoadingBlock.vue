<script setup lang="ts">
/**
 * 加载占位：骨架条（默认）或行内 spinner。
 * rows 控制骨架行数，用于表格/列表首屏加载。
 */
withDefaults(
  defineProps<{
    /** 骨架行数 */
    rows?: number
    /** 紧凑模式（行高更小） */
    compact?: boolean
  }>(),
  { rows: 4, compact: false },
)
</script>

<template>
  <div class="loading-block" :class="{ 'loading-block--compact': compact }" role="status" aria-label="加载中">
    <div v-for="i in rows" :key="i" class="loading-block__row">
      <span class="loading-block__bar" :style="{ width: `${88 - ((i * 13) % 46)}%` }" />
    </div>
  </div>
</template>

<style scoped>
.loading-block { display: flex; flex-direction: column; gap: 10px; padding: var(--sp-2) 0; }
.loading-block__row { height: 18px; }
.loading-block--compact .loading-block__row { height: 14px; }
.loading-block__bar {
  display: block;
  height: 100%;
  border-radius: var(--radius-sm);
  background: linear-gradient(90deg, var(--bg-overlay) 25%, var(--bg-hover) 37%, var(--bg-overlay) 63%);
  background-size: 400% 100%;
  animation: shimmer 1.4s ease infinite;
}
@keyframes shimmer {
  0% { background-position: 100% 50%; }
  100% { background-position: 0 50%; }
}
@media (prefers-reduced-motion: reduce) {
  .loading-block__bar { animation: none; }
}
</style>
