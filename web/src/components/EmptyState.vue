<script setup lang="ts">
import Icon from './Icon.vue'
defineProps<{ message?: string }>()
defineSlots<{ action?: {} }>()
</script>

<template>
  <div class="empty-state">
    <Icon name="info" :size="32" class="ic" />
    <p class="msg">{{ message ?? '暂无数据' }}</p>
    <div v-if="$slots.action">
      <slot name="action" />
    </div>
  </div>
</template>

<style scoped>
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: var(--sp-8) var(--sp-6);
  gap: var(--sp-3);
}
.ic { color: var(--text-faint); }
.msg { color: var(--text-sub); font-size: var(--fs-md); }
</style>
