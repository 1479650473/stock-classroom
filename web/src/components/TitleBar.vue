<script setup lang="ts">
import { ref } from 'vue'
import Icon from './Icon.vue'
import { isTauri, winMinimize, winToggleMaximize, winClose, winStartDrag } from '@/lib/tauri'
import { useAppStore } from '@/stores/app'

const app = useAppStore()
const emit = defineEmits<{ (e: 'open-search'): void; (e: 'toggle-chat'): void }>()

const maximized = ref(false)
async function toggleMax() {
  await winToggleMaximize()
  maximized.value = !maximized.value
}

const themes: Array<{ key: 'graphite' | 'obsidian' | 'ivory'; label: string }> = [
  { key: 'graphite', label: '石墨' },
  { key: 'obsidian', label: '黑曜' },
  { key: 'ivory', label: '象牙' },
]
function cycleTheme() {
  const i = themes.findIndex((t) => t.key === app.theme)
  app.setTheme(themes[(i + 1) % themes.length].key)
}

const inTauri = isTauri()
</script>

<template>
  <header class="titlebar" @mousedown.self="winStartDrag" @dblclick.self="toggleMax">
    <div class="brand" @mousedown="winStartDrag">
      <img src="/logo.svg" alt="logo" class="logo" draggable="false" />
      <span class="name">股票教室</span>
      <span class="ver">v5.0</span>
    </div>

    <button class="search" @click="emit('open-search')" title="搜索股票 (Ctrl+K)">
      <Icon name="search" :size="15" />
      <span class="ph">搜索股票 / 代码</span>
      <kbd>Ctrl K</kbd>
    </button>

    <div class="actions">
      <button class="tb-btn" @click="cycleTheme" :title="'切换主题（当前：' + themes.find(t=>t.key===app.theme)?.label + '）'">
        <Icon name="layers" :size="16" />
      </button>
      <button class="tb-btn" @click="emit('toggle-chat')" title="AI 助手">
        <Icon name="chat" :size="16" />
      </button>
      <router-link to="/settings" class="tb-btn" title="设置">
        <Icon name="settings" :size="16" />
      </router-link>
      <div v-if="inTauri" class="win-controls">
        <button class="wc" @click="winMinimize" title="最小化"><Icon name="minus" :size="14" /></button>
        <button class="wc" @click="toggleMax" :title="maximized ? '还原' : '最大化'">
          <Icon :name="maximized ? 'restore' : 'maximize'" :size="13" />
        </button>
        <button class="wc close" @click="winClose" title="关闭"><Icon name="close" :size="14" /></button>
      </div>
    </div>
  </header>
</template>

<style scoped>
.titlebar {
  height: var(--titlebar-h);
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  padding: 0 var(--sp-3) 0 var(--sp-4);
  background: var(--bg-panel);
  border-bottom: 1px solid var(--border-soft);
  flex: none;
  -webkit-app-region: drag;
}
.brand { display: flex; align-items: center; gap: var(--sp-2); -webkit-app-region: drag; }
.logo { width: 22px; height: 22px; display: block; }
.name { font-size: var(--fs-lg); font-weight: 700; letter-spacing: 1px; color: var(--gold); }
.ver {
  font-size: var(--fs-xs); color: var(--text-faint);
  border: 1px solid var(--border); border-radius: var(--radius-pill);
  padding: 1px 7px;
}
.search {
  -webkit-app-region: no-drag;
  display: flex; align-items: center; gap: var(--sp-2);
  margin-left: var(--sp-4);
  background: var(--bg); color: var(--text-faint);
  border: 1px solid var(--border); border-radius: var(--radius-md);
  padding: 5px 10px; min-width: 220px; cursor: pointer;
  transition: border-color var(--dur-fast), color var(--dur-fast);
  font-size: var(--fs-sm);
}
.search:hover { border-color: var(--accent); color: var(--text-sub); }
.search .ph { flex: 1; text-align: left; }
.search kbd {
  font-family: var(--font-mono); font-size: 10px; color: var(--text-faint);
  border: 1px solid var(--border); border-radius: 4px; padding: 0 5px;
}
.actions { margin-left: auto; display: flex; align-items: center; gap: var(--sp-1); -webkit-app-region: no-drag; }
.tb-btn {
  display: inline-flex; align-items: center; justify-content: center;
  width: 32px; height: 32px; border-radius: var(--radius-sm);
  background: transparent; border: none; color: var(--text-sub); cursor: pointer;
  transition: background var(--dur-fast), color var(--dur-fast);
}
.tb-btn:hover { background: var(--bg-raised); color: var(--text); }
.win-controls { display: flex; gap: 2px; margin-left: var(--sp-2); }
.wc {
  display: inline-flex; align-items: center; justify-content: center;
  width: 40px; height: var(--titlebar-h); border: none; background: transparent;
  color: var(--text-sub); cursor: pointer; transition: background var(--dur-fast), color var(--dur-fast);
}
.wc:hover { background: var(--bg-raised); color: var(--text); }
.wc.close:hover { background: var(--up); color: #fff; }
</style>
