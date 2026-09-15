<script setup lang="ts">
import { useToastStore } from '@/stores/toast'
import Icon from './Icon.vue'

const store = useToastStore()
const iconFor = (k: string) => (k === 'success' ? 'check' : k === 'error' ? 'alert' : 'info')
</script>

<template>
  <transition-group name="toast" tag="div" class="toast-host">
    <div v-for="t in store.toasts" :key="t.id" class="toast" :class="t.kind" @click="store.dismiss(t.id)">
      <span class="toast__icon"><Icon :name="iconFor(t.kind)" :size="14" /></span>
      <span class="toast__text">{{ t.text }}</span>
      <span class="toast__timer" :style="{ animationDuration: `${t.timeoutMs}ms` }" />
    </div>
  </transition-group>
</template>

<style scoped>
.toast-host {
  position: fixed; right: var(--sp-5); bottom: var(--sp-5);
  display: flex; flex-direction: column; gap: var(--sp-2); z-index: 9999;
}
.toast {
  position: relative;
  display: flex; align-items: center; gap: var(--sp-3);
  min-width: 240px;
  background: var(--glass); color: var(--text);
  backdrop-filter: blur(14px) saturate(1.2);
  -webkit-backdrop-filter: blur(14px) saturate(1.2);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-lg);
  padding: 11px 14px 12px;
  box-shadow: var(--shadow-pop);
  font-size: var(--fs-md);
  cursor: pointer;
  overflow: hidden;
  max-width: 380px;
}
/* 左侧强调条 + 图标气泡 */
.toast::before {
  content: '';
  position: absolute;
  left: 0; top: 0; bottom: 0;
  width: 3px;
  background: var(--accent);
}
.toast__icon {
  flex: none;
  display: grid; place-items: center;
  width: 24px; height: 24px;
  border-radius: var(--radius-pill);
  background: color-mix(in srgb, var(--accent) 18%, transparent);
  color: var(--accent);
}
.toast__text { flex: 1; min-width: 0; line-height: 1.45; }
.toast.success::before { background: var(--down); }
.toast.success .toast__icon { background: color-mix(in srgb, var(--down) 18%, transparent); color: var(--down); }
.toast.error::before { background: var(--up); }
.toast.error .toast__icon { background: color-mix(in srgb, var(--up) 18%, transparent); color: var(--up); }
/* 自动消失进度线 */
.toast__timer {
  position: absolute;
  left: 0; bottom: 0;
  height: 2px;
  width: 100%;
  transform-origin: left center;
  background: linear-gradient(90deg, color-mix(in srgb, currentColor 60%, transparent), transparent);
  animation-name: toast-countdown;
  animation-timing-function: linear;
  animation-fill-mode: forwards;
}
@keyframes toast-countdown {
  from { transform: scaleX(1); }
  to { transform: scaleX(0); }
}
.toast-enter-active { transition: opacity var(--dur) var(--ease), transform var(--dur) var(--ease-spring); }
.toast-leave-active { transition: opacity var(--dur-fast) var(--ease), transform var(--dur-fast) var(--ease); }
.toast-enter-from { opacity: 0; transform: translateX(24px) scale(0.96); }
.toast-leave-to { opacity: 0; transform: translateX(12px) scale(0.98); }
@media (prefers-reduced-motion: reduce) {
  .toast__timer { animation: none; opacity: 0.4; }
}
</style>
