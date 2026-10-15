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
    /**
     * 嵌入式：**不渲染自己的标题区**，只保留内容容器。
     *
     * 用途：某个视图原本是独立页面（有自己的 title/subtitle），现在被降级成
     * 另一个页面的页内 Tab（如「套利」并入「行情」）。此时外层页面已经有标题，
     * 再渲染一次就会出现"两层标题"，既重复又浪费纵向空间。
     * 与 `PageHeader` 的 `embedded` 语义一致，保持全站两种容器行为统一。
     */
    embedded?: boolean
    /**
     * actions 移到内容流里（仅在 `embedded` 时有意义）。
     *
     * 为什么需要它：标题区被隐藏后，`#actions` 槽也会跟着没地方放。
     * 但有些视图把**日期、同步按钮、设置入口**都放在 actions 里 ——
     * 直接隐藏会丢功能。开启本项后，actions 改为在内容流顶部单独渲染一行，
     * 既保留了入口，又不会重复标题。
     */
    actionsInline?: boolean
  }>(),
  { contained: true, embedded: false, actionsInline: false },
)
</script>

<template>
  <div class="app-page" :class="{ 'app-page--contained': contained }">
    <header v-if="!embedded" class="app-page__head">
      <div class="app-page__titles">
        <h1 class="app-page__title">{{ title }}</h1>
        <p v-if="subtitle" class="app-page__subtitle">{{ subtitle }}</p>
      </div>
      <div v-if="$slots.actions" class="app-page__actions">
        <slot name="actions" />
      </div>
    </header>
    <!-- 嵌入且要求内联时：actions 作为内容流的第一行（不重复标题） -->
    <div v-if="embedded && actionsInline && $slots.actions" class="app-page__actions app-page__actions--inline">
      <slot name="actions" />
    </div>
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
  letter-spacing: 0;
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
/* 内联 actions：靠右对齐，形成"日期 + 按钮"的一行工具条 */
.app-page__actions--inline {
  justify-content: flex-end;
  margin-top: calc(var(--sp-2) * -1);
}
</style>
