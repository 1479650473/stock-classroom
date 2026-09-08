<script setup lang="ts">
import Icon from '@/components/Icon.vue'

/**
 * 分段控件：少量互斥选项的切换（周期、买卖方向、视图模式）。
 * 比下拉更直观，比一排按钮更整洁。
 */
withDefaults(
  defineProps<{
    modelValue: string
    options: { value: string; label: string; icon?: string }[]
    size?: 'md' | 'sm'
    /** 等分占满宽度 */
    block?: boolean
  }>(),
  { size: 'md', block: false },
)

const emit = defineEmits<{ 'update:modelValue': [v: string] }>()
</script>

<template>
  <div class="seg" :class="[`seg--${size}`, { 'seg--block': block }]" role="tablist">
    <button
      v-for="opt in options"
      :key="opt.value"
      class="seg__item"
      :class="{ 'is-active': modelValue === opt.value }"
      role="tab"
      :aria-selected="modelValue === opt.value"
      @click="emit('update:modelValue', opt.value)"
    >
      <Icon v-if="opt.icon" :name="opt.icon" :size="13" />
      <span>{{ opt.label }}</span>
    </button>
  </div>
</template>

<style scoped>
.seg {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 3px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-control);
}
.seg--block { display: flex; width: 100%; }
.seg--block .seg__item { flex: 1; }
.seg__item {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  height: 26px;
  padding: 0 12px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--text-sub);
  font-size: var(--fs-sm);
  font-weight: 500;
  white-space: nowrap;
  cursor: pointer;
  transition: all var(--dur-fast) var(--ease);
}
.seg--sm .seg__item { height: 22px; padding: 0 9px; font-size: var(--fs-xs); }
.seg__item:hover { color: var(--text); }
.seg__item.is-active {
  background: var(--bg-raised);
  color: var(--text);
  box-shadow: var(--shadow-1);
}
</style>
