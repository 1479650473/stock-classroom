<script setup lang="ts">
/**
 * 表单字段：统一 label / 控件 / 提示 / 错误 的排布。
 * 控件本身用全局 .ui-input / .ui-select 类，保证全站高度一致。
 */
withDefaults(
  defineProps<{
    label?: string
    hint?: string
    error?: string
    required?: boolean
  }>(),
  { required: false },
)
</script>

<template>
  <label class="form-field">
    <span v-if="label" class="form-field__label">
      {{ label }}<span v-if="required" class="form-field__req">*</span>
    </span>
    <slot />
    <span v-if="error" class="form-field__error">{{ error }}</span>
    <span v-else-if="hint" class="form-field__hint">{{ hint }}</span>
  </label>
</template>

<style scoped>
.form-field { display: flex; flex-direction: column; gap: 5px; min-width: 0; }
.form-field__label {
  font-size: var(--fs-sm);
  color: var(--text-sub);
  font-weight: 500;
}
.form-field__req { color: var(--up); margin-left: 2px; }
.form-field__hint { font-size: var(--fs-xs); color: var(--text-faint); }
.form-field__error { font-size: var(--fs-xs); color: var(--up); }
</style>
