<script setup lang="ts">
import { useRoute } from 'vue-router'
import Icon from './Icon.vue'
import { NAV } from '@/lib/nav'
import { isTauri } from '@/lib/tauri'

const route = useRoute()
</script>

<template>
  <nav class="sidenav">
    <div v-for="(group, gi) in NAV" :key="gi" class="group">
      <div v-if="group.label" class="group-label">{{ group.label }}</div>
      <router-link
        v-for="item in group.items"
        :key="item.path"
        :to="item.path"
        class="nav-item"
        :class="{ active: route.path === item.path }"
        :title="item.hint || item.title"
      >
        <span class="bar" />
        <Icon :name="item.icon" :size="17" class="ic" />
        <span class="txt">{{ item.title }}</span>
      </router-link>
    </div>
    <div class="spacer" />
    <div class="foot muted">v5.2 · {{ isTauri() ? '桌面端' : 'Web' }}</div>
  </nav>
</template>

<style scoped>
.sidenav {
  width: var(--nav-w);
  flex: none;
  background: var(--bg-panel);
  border-right: 1px solid var(--border-soft);
  display: flex;
  flex-direction: column;
  padding: var(--sp-3) var(--sp-2);
  overflow-y: auto;
}
.group { margin-bottom: var(--sp-3); }
.group-label {
  font-size: var(--fs-xs);
  color: var(--text-faint);
  letter-spacing: 1.5px;
  padding: var(--sp-2) var(--sp-3);
  text-transform: none;
}
.nav-item {
  position: relative;
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  padding: 9px var(--sp-3);
  margin: 2px 0;
  border-radius: var(--radius-sm);
  color: var(--text-sub);
  font-size: var(--fs-md);
  transition: background var(--dur-fast) var(--ease), color var(--dur-fast) var(--ease);
}
.nav-item .ic { color: var(--text-faint); transition: color var(--dur-fast); }
.nav-item:hover { background: var(--bg-raised); color: var(--text); transform: translateX(2px); }
.nav-item { will-change: transform; }
.nav-item:hover .ic { color: var(--text); }
.nav-item.active {
  background: linear-gradient(90deg, var(--gold-dim), transparent 92%);
  color: var(--gold);
  font-weight: 600;
}
.nav-item.active .ic { color: var(--gold); }
.nav-item .bar {
  position: absolute; left: 0; top: 20%; bottom: 20%;
  width: 3px; border-radius: 2px; background: transparent;
  transition: background var(--dur-fast);
}
.nav-item.active .bar {
  background: var(--gold);
  box-shadow: 0 0 10px color-mix(in srgb, var(--gold) 60%, transparent);
}
.nav-item .txt { flex: 1; }
.spacer { flex: 1; }
.foot { font-size: var(--fs-xs); text-align: center; padding: var(--sp-2); letter-spacing: 0.5px; }
</style>
