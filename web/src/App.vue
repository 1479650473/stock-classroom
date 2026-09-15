<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useAppStore } from '@/stores/app'
import { useJobsStore } from '@/stores/jobs'
import TitleBar from '@/components/TitleBar.vue'
import SideNav from '@/components/SideNav.vue'
import ToastHost from '@/components/ToastHost.vue'
import SearchPalette from '@/components/SearchPalette.vue'

const app = useAppStore()
const jobs = useJobsStore()
const searchOpen = ref(false)

onMounted(() => {
  app.init()
  // 恢复上次会话中未完成/刚完成的后台任务（刷新页面后进度不丢）
  jobs.restore()
})
</script>

<template>
  <div v-if="app.ready" class="shell">
    <TitleBar @open-search="searchOpen = true" />
    <div class="body">
      <SideNav />
      <main class="content">
        <router-view v-slot="{ Component }">
          <transition name="page" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </main>
    </div>
  </div>

  <SearchPalette :open="searchOpen" @close="searchOpen = false" />
  <ToastHost />
</template>

<style scoped>
.shell {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: var(--bg);
}
.body {
  position: relative;
  flex: 1;
  display: flex;
  overflow: hidden;
}
/* 环境底纹：顶部一层极淡径向光 + 细网格，给数据面增加纵深（不拦截事件） */
.body::before {
  content: '';
  position: absolute;
  inset: 0 0 auto 0;
  height: 380px;
  background:
    radial-gradient(120% 100% at 50% 0%, var(--grid-line) 0%, transparent 72%),
    radial-gradient(60% 60% at 78% 0%, color-mix(in srgb, var(--gold) 5%, transparent) 0%, transparent 70%),
    linear-gradient(var(--grid-line) 1px, transparent 1px) 0 0 / var(--grid-size) var(--grid-size),
    linear-gradient(90deg, var(--grid-line) 1px, transparent 1px) 0 0 / var(--grid-size) var(--grid-size);
  pointer-events: none;
  z-index: 0;
}
.content {
  position: relative;
  z-index: 1;
  flex: 1;
  overflow-y: auto;
  padding: var(--sp-5);
}
.page-enter-active,
.page-leave-active {
  transition: opacity var(--dur) var(--ease), transform var(--dur) var(--ease);
}
.page-enter-from {
  opacity: 0;
  transform: translateY(6px);
}
.page-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}
</style>
