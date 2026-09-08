<script setup lang="ts">
import { onBeforeUnmount, watch } from 'vue'
import Icon from '@/components/Icon.vue'

/**
 * 右侧抽屉：承载"高级设置 / 详情"等渐进披露内容。
 * 打开时锁定 body 滚动，ESC 或点击遮罩关闭。
 */
const props = withDefaults(
  defineProps<{
    open: boolean
    title?: string
    desc?: string
    width?: number
  }>(),
  { width: 400 },
)

const emit = defineEmits<{ close: []; 'update:open': [v: boolean] }>()

function close() {
  emit('update:open', false)
  emit('close')
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') close()
}

watch(
  () => props.open,
  (v) => {
    document.body.style.overflow = v ? 'hidden' : ''
    if (v) window.addEventListener('keydown', onKeydown)
    else window.removeEventListener('keydown', onKeydown)
  },
)

onBeforeUnmount(() => {
  document.body.style.overflow = ''
  window.removeEventListener('keydown', onKeydown)
})
</script>

<template>
  <Teleport to="body">
    <Transition name="drawer">
      <div v-if="open" class="drawer-root">
        <div class="drawer-mask" @click="close" />
        <aside class="drawer" :style="{ width: `${width}px` }" role="dialog" aria-modal="true">
          <header class="drawer__head">
            <div>
              <h3 v-if="title" class="drawer__title">{{ title }}</h3>
              <p v-if="desc" class="drawer__desc">{{ desc }}</p>
            </div>
            <button class="ui-btn ui-btn--ghost ui-btn--icon ui-btn--sm" title="关闭" @click="close">
              <Icon name="close" :size="15" />
            </button>
          </header>
          <div class="drawer__body"><slot /></div>
          <footer v-if="$slots.footer" class="drawer__foot"><slot name="footer" /></footer>
        </aside>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.drawer-root { position: fixed; inset: 0; z-index: 200; }
.drawer-mask {
  position: absolute;
  inset: 0;
  background: rgba(4, 6, 9, 0.55);
  backdrop-filter: blur(1px);
}
.drawer {
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  max-width: 92vw;
  display: flex;
  flex-direction: column;
  background: var(--bg-panel);
  border-left: 1px solid var(--border);
  box-shadow: var(--shadow-3);
}
.drawer__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--sp-3);
  padding: var(--sp-4) var(--sp-5);
  border-bottom: 1px solid var(--border-soft);
}
.drawer__title { margin: 0; font-size: var(--fs-lg); font-weight: 600; color: var(--text); }
.drawer__desc { margin: 3px 0 0; font-size: var(--fs-sm); color: var(--text-faint); }
.drawer__body { flex: 1; overflow-y: auto; padding: var(--sp-5); }
.drawer__foot {
  display: flex;
  justify-content: flex-end;
  gap: var(--sp-2);
  padding: var(--sp-4) var(--sp-5);
  border-top: 1px solid var(--border-soft);
}
.drawer-enter-active, .drawer-leave-active { transition: opacity var(--dur) var(--ease); }
.drawer-enter-active .drawer, .drawer-leave-active .drawer { transition: transform var(--dur) var(--ease); }
.drawer-enter-from, .drawer-leave-to { opacity: 0; }
.drawer-enter-from .drawer, .drawer-leave-to .drawer { transform: translateX(100%); }
</style>
