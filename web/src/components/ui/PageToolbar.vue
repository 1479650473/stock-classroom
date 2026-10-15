<script setup lang="ts">
import Icon from '@/components/Icon.vue'

/**
 * 页面工具条：Tab 切换 + 右侧额外操作 + 高级设置入口。
 * 每个多视图页面（交易/策略/行情/AI/数据）都复用它。
 */
withDefaults(
  defineProps<{
    modelValue: string
    tabs: {
      value: string
      label: string
      icon?: string
      /**
       * 角标：贴在标签右侧的小字（如「已停用」）。
       *
       * 为什么不直接拼进 label：label 参与宽度计算与换行，写成
       * 「AI 操盘手（已停用）」会让 Tab 很长、且把状态和真名字糊在一起。
       * 单独角标既能独立样式化，以后也能按状态换色。
       *
       * 刻意**不**用它禁用点击：停用的功能仍应可进入（查历史、看旧决策、重新启用），
       * 角标只负责"如实告知状态"。
       */
      badge?: string
    }[]
    /** 是否显示"高级设置"按钮 */
    advanced?: boolean
  }>(),
  { advanced: false },
)

const emit = defineEmits<{
  'update:modelValue': [v: string]
  advanced: []
}>()
</script>

<template>
  <div class="page-toolbar">
    <nav class="page-toolbar__tabs" role="tablist">
      <button
        v-for="t in tabs"
        :key="t.value"
        class="page-toolbar__tab"
        :class="{ 'is-active': modelValue === t.value }"
        role="tab"
        :aria-selected="modelValue === t.value"
        @click="emit('update:modelValue', t.value)"
      >
        <Icon v-if="t.icon" :name="t.icon" :size="14" />
        <span>{{ t.label }}</span>
        <span v-if="t.badge" class="page-toolbar__badge">{{ t.badge }}</span>
      </button>
    </nav>
    <div class="page-toolbar__extra">
      <slot name="extra" />
      <button v-if="advanced" class="ui-btn ui-btn--ghost ui-btn--sm" @click="emit('advanced')">
        <Icon name="settings" :size="13" />
        <span>高级设置</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.page-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-4);
  border-bottom: 1px solid var(--border-soft);
  flex-wrap: wrap;
}
.page-toolbar__tabs { display: flex; align-items: center; gap: 2px; overflow-x: auto; }
.page-toolbar__tab {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 40px;
  padding: 0 14px;
  border: 0;
  border-bottom: 2px solid transparent;
  background: transparent;
  color: var(--text-sub);
  font-size: var(--fs-md);
  font-weight: 500;
  white-space: nowrap;
  cursor: pointer;
  transition: color var(--dur-fast) var(--ease);
}
.page-toolbar__tab:hover { color: var(--text); }
.page-toolbar__tab.is-active {
  color: var(--text);
  border-bottom-color: var(--gold);
  font-weight: 600;
}
/* 角标：贴右侧的小字。用中性灰底，避免和"红涨绿跌"的语义色抢注意力 */
.page-toolbar__badge {
  padding: 1px 6px;
  border-radius: var(--radius-pill);
  background: var(--bg-overlay);
  border: 1px solid var(--border-soft);
  color: var(--text-faint);
  font-size: var(--fs-xs);
  font-weight: 400;
  line-height: 1.5;
}
:root[data-motion='reduced'] .page-toolbar__badge { transition: none; }
.page-toolbar__extra { display: flex; align-items: center; gap: var(--sp-2); }
</style>
