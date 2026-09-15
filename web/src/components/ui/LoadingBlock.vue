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
    /** 形态：rows 文本行 / cards 卡片块 / table 表格行 */
    variant?: 'rows' | 'cards' | 'table'
  }>(),
  { rows: 4, compact: false, variant: 'rows' },
)
</script>

<template>
  <div
    class="loading-block"
    :class="[`loading-block--${variant}`, { 'loading-block--compact': compact }]"
    role="status"
    aria-label="加载中"
  >
    <template v-if="variant === 'cards'">
      <div v-for="i in rows" :key="i" class="loading-block__card">
        <span class="loading-block__bar" style="width: 38%" />
        <span class="loading-block__bar" style="width: 72%; height: 22px" />
        <span class="loading-block__bar" style="width: 54%" />
      </div>
    </template>
    <template v-else>
      <div v-for="i in rows" :key="i" class="loading-block__row">
        <span class="loading-block__bar" :style="{ width: `${88 - ((i * 13) % 46)}%` }" />
      </div>
    </template>
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
/* 卡片形态：更接近真实内容骨架 */
.loading-block--cards { flex-direction: row; flex-wrap: wrap; }
.loading-block__card {
  flex: 1 1 220px;
  min-width: 180px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: var(--sp-4);
  border: 1px solid var(--border-soft);
  border-radius: var(--radius-lg);
  background: var(--bg-raised);
}
.loading-block__card .loading-block__bar { height: 14px; }
/* 表格形态：行更密、带分隔线 */
.loading-block--table .loading-block__row { height: 26px; border-bottom: 1px solid var(--border-soft); }
@media (prefers-reduced-motion: reduce) {
  .loading-block__bar { animation: none; }
}
</style>
