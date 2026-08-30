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
  transition: border-color var(--dur-fast) var(--ease);
}
.card--hl:hover {
  border-color: var(--accent);
}
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
