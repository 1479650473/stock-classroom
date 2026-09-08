<script setup lang="ts">
import { ref, onBeforeUnmount } from 'vue'
import Icon from '@/components/Icon.vue'

/**
 * 二次确认按钮：危险操作（删除/清空/重置）必须用它。
 * 首次点击进入"确认"态，超时或失焦自动还原。
 */
const props = withDefaults(
  defineProps<{
    label: string
    confirmLabel?: string
    /** 危险操作用红色 */
    danger?: boolean
    disabled?: boolean
    /** 确认态持续毫秒数 */
    timeout?: number
    size?: 'md' | 'sm'
  }>(),
  { confirmLabel: '确认', danger: false, disabled: false, timeout: 3000, size: 'md' },
)

const emit = defineEmits<{ confirm: [] }>()
const arming = ref(false)
let timer: ReturnType<typeof setTimeout> | null = null

function clearTimer() {
  if (timer) { clearTimeout(timer); timer = null }
}

function onClick() {
  if (props.disabled) return
  if (!arming.value) {
    arming.value = true
    clearTimer()
    timer = setTimeout(() => { arming.value = false }, props.timeout)
    return
  }
  clearTimer()
  arming.value = false
  emit('confirm')
}

function onBlur() {
  clearTimer()
  arming.value = false
}

onBeforeUnmount(clearTimer)
</script>

<template>
  <button
    class="ui-btn"
    :class="[
      arming ? 'ui-btn--danger' : (danger ? 'ui-btn--ghost' : ''),
      size === 'sm' ? 'ui-btn--sm' : '',
      arming ? 'is-arming' : '',
    ]"
    :disabled="disabled"
    @click="onClick"
    @blur="onBlur"
  >
    <Icon v-if="danger && !arming" name="alert" :size="13" />
    {{ arming ? confirmLabel : label }}
  </button>
</template>

<style scoped>
.is-arming { font-weight: 600; }
</style>
