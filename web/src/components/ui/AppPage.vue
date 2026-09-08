<script setup lang="ts">
/**
 * 页面容器：统一标题区 + 操作区 + 内容区，限制最大宽度并居中。
 * 所有主页面都应使用它作为根，保证全站页面骨架一致。
 */
withDefaults(
  defineProps<{
    title: string
    subtitle?: string
    /** 内容是否限制最大宽度并居中（默认 true） */
    contained?: boolean
  }>(),
  { contained: true },
)
</script>

<template>
  <div class="app-page" :class="{ 'app-page--contained': contained }">
    <header class="app-page__head">
      <div class="app-page__titles">
        <h1 class="app-page__title">{{ title }}</h1>
        <p v-if="subtitle" class="app-page__subtitle">{{ subtitle }}</p>
      </div>
      <div v-if="$slots.actions" class="app-page__actions">
        <slot name="actions" />
      </div>
    </header>
    <slot />
  </div>
</template>

<style scoped>
.app-page {
  display: flex;
  flex-direction: column;
  gap: var(--section-gap);
  width: 100%;
}
.app-page--contained {
  max-width: var(--page-max);
  margin: 0 auto;
}
.app-page__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--sp-4);
  flex-wrap: wrap;
  min-height: 44px;
}
.app-page__title {
  margin: 0;
  font-size: var(--fs-2xl);
  font-weight: 650;
  line-height: 1.25;
  letter-spacing: -0.01em;
  color: var(--text);
}
.app-page__subtitle {
  margin: 5px 0 0;
  font-size: var(--fs-md);
  line-height: 1.4;
  color: var(--text-sub);
}
.app-page__actions {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-wrap: wrap;
}
</style>
