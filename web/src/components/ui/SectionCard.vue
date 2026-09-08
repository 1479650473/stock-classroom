<script setup lang="ts">
/**
 * 区块卡片：页面内的功能分区。标题/说明在左，操作在右，内容区可选内边距。
 * 用于替代各页手写的 Card + 标题结构。
 */
withDefaults(
  defineProps<{
    title?: string
    desc?: string
    /** 内容区是否加内边距（默认 true） */
    padded?: boolean
  }>(),
  { padded: true },
)
</script>

<template>
  <section class="sec-card">
    <header v-if="title || desc || $slots.actions" class="sec-card__head">
      <div class="sec-card__titles">
        <h2 v-if="title" class="sec-card__title">{{ title }}</h2>
        <p v-if="desc" class="sec-card__desc">{{ desc }}</p>
      </div>
      <div v-if="$slots.actions" class="sec-card__actions">
        <slot name="actions" />
      </div>
    </header>
    <div class="sec-card__body" :class="{ 'sec-card__body--pad': padded }">
      <slot />
    </div>
  </section>
</template>

<style scoped>
.sec-card {
  background: var(--bg-raised);
  border: 1px solid var(--border-soft);
  border-radius: var(--radius-lg);
  overflow: hidden;
}
.sec-card__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-4);
  padding: var(--sp-4) var(--sp-5);
  border-bottom: 1px solid var(--border-soft);
}
.sec-card__titles { min-width: 0; }
.sec-card__title {
  margin: 0;
  font-size: var(--fs-lg);
  font-weight: 600;
  color: var(--text);
}
.sec-card__desc {
  margin: 3px 0 0;
  font-size: var(--fs-sm);
  color: var(--text-faint);
}
.sec-card__actions {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex: none;
}
.sec-card__body { padding: 0; }
.sec-card__body--pad { padding: var(--sp-5); }
</style>
