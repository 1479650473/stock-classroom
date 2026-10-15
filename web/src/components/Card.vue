<script setup lang="ts">
defineProps<{ title?: string; padding?: boolean; highlight?: boolean; href?: string }>()
defineSlots<{ default?: {}; header?: {}; footer?: {} }>()
</script>

<template>
  <div
    class="card"
    :class="{ 'card--hl': highlight, 'card--pad': padding ?? true }"
  >
    <div v-if="title || $slots.header" class="card-hd">
      <slot name="header">
        <span class="card-title">{{ title }}</span>
      </slot>
    </div>
    <div class="card-bd">
      <slot />
    </div>
    <div v-if="$slots.footer" class="card-ft">
      <slot name="footer" />
    </div>
  </div>
</template>

<style scoped>
.card {
  background: var(--bg-raised);
  border: 1px solid var(--border-soft);
  border-radius: var(--radius-lg);
  /* 悬停时边框提亮 + 轻微抬升（只用 transform，不触发重排） */
  transition: border-color var(--dur-fast) var(--ease),
              transform var(--dur) var(--ease-out),
              box-shadow var(--dur) var(--ease-out);
}
/* 只有"可交互"卡片才抬升；纯展示卡片不该因为鼠标划过而跳，
   否则整页都在抖。带 href 或 highlight 的视为可交互。 */
.card--hl:hover,
a > .card:hover {
  border-color: var(--accent);
}
.card:hover:has(.card-hd) {
  box-shadow: var(--shadow-2);
}
:root[data-motion='reduced'] .card:hover { transform: none; box-shadow: none; }
.card--pad {
  padding: var(--sp-4);
}
.card-hd {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--sp-4);
  border-bottom: 1px solid var(--border-soft);
}
.card-title {
  font-weight: 600;
  font-size: var(--fs-md);
  color: var(--text);
}
.card-bd {
  padding: var(--sp-4);
}
</style>
