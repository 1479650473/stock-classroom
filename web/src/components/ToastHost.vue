<script setup lang="ts">
import { useToastStore } from '@/stores/toast'
import Icon from './Icon.vue'

const store = useToastStore()
const iconFor = (k: string) => (k === 'success' ? 'check' : k === 'error' ? 'alert' : 'info')
</script>

<template>
  <transition-group name="toast" tag="div" class="toast-host">
    <div v-for="t in store.toasts" :key="t.id" class="toast" :class="t.kind" @click="store.dismiss(t.id)">
      <Icon :name="iconFor(t.kind)" :size="15" />
      <span>{{ t.text }}</span>
    </div>
  </transition-group>
</template>

<style scoped>
.toast-host {
  position: fixed; right: var(--sp-5); bottom: var(--sp-5);
  display: flex; flex-direction: column; gap: var(--sp-2); z-index: 9999;
}
.toast {
  display: flex; align-items: center; gap: var(--sp-2);
  background: var(--bg-overlay); color: var(--text);
  border: 1px solid var(--border-strong); border-radius: var(--radius-md);
  padding: 10px 14px; box-shadow: var(--shadow-pop);
  font-size: var(--fs-md); cursor: pointer; max-width: 380px;
}
.toast.success { border-left: 3px solid var(--down); }
.toast.error { border-left: 3px solid var(--up); }
.toast.info { border-left: 3px solid var(--accent); }
.toast-enter-active, .toast-leave-active { transition: all var(--dur) var(--ease); }
.toast-enter-from { opacity: 0; transform: translateX(20px); }
.toast-leave-to { opacity: 0; transform: translateY(8px); }
</style>
