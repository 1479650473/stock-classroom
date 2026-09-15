<script setup lang="ts">
/**
 * 悬浮提示：数据密集界面里用来解释指标口径、按钮作用。
 * 纯 CSS 实现（::after 读 data-tip），不依赖浮层定位库；需长文本时用 \n 换行。
 */
withDefaults(
  defineProps<{
    /** 提示内容（\n 换行） */
    text: string
    /** 触发方式：hover（默认）或 always（常显，用于图例说明） */
    mode?: 'hover' | 'always'
  }>(),
  { mode: 'hover' },
)
</script>

<template>
  <span class="ui-tip tip" :class="{ 'ui-tip--always': mode === 'always' }" :data-tip="text" tabindex="0">
    <slot />
  </span>
</template>

<style scoped>
.ui-tip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  cursor: help;
}
.ui-tip:focus { outline: none; }
.ui-tip--always::after { opacity: 1; transform: translate(-50%, 0); }
</style>
