<script setup lang="ts">
import Icon from '@/components/Icon.vue'

/**
 * 空状态引导：图标 + 标题 + 说明 + 主操作按钮。
 * 所有空数据场景必须使用它，并给出"下一步做什么"。
 */
withDefaults(
  defineProps<{
    icon?: string
    title: string
    desc?: string
  }>(),
  { icon: 'info' },
)
</script>

<template>
  <div class="empty-guide">
    <div class="empty-guide__icon"><Icon :name="icon" :size="22" /></div>
    <div class="empty-guide__title">{{ title }}</div>
    <p v-if="desc" class="empty-guide__desc">{{ desc }}</p>
    <div v-if="$slots.action" class="empty-guide__action">
      <slot name="action" />
    </div>
  </div>
</template>

<style scoped>
.empty-guide {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--sp-2);
  padding: var(--sp-10) var(--sp-5);
  text-align: center;
}
.empty-guide__icon {
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  border-radius: var(--radius-pill);
  background: var(--bg-overlay);
  color: var(--text-faint);
  margin-bottom: var(--sp-1);
}
.empty-guide__title { font-size: var(--fs-md); font-weight: 600; color: var(--text); }
.empty-guide__desc {
  margin: 0;
  max-width: 360px;
  font-size: var(--fs-sm);
  line-height: 1.6;
  color: var(--text-faint);
}
.empty-guide__action { margin-top: var(--sp-3); }
</style>
