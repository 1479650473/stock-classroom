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

/** 需要保活的主页面（组件名 = 文件名）：工作台/行情/策略/交易/AI/数据 */
const KEEP_ALIVE = ['Dashboard', 'Market', 'Strategy', 'Trade', 'AI', 'Data']

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
        <!-- KeepAlive：主页面切走再切回复用实例（不重新挂载、不重新请求）；
             新鲜度交给 API 层 TTL + 各页 onActivated，不会看到陈旧数据。 -->
        <router-view v-slot="{ Component }">
          <transition name="page" mode="out-in">
            <keep-alive :include="KEEP_ALIVE">
              <component :is="Component" />
            </keep-alive>
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
/* 页面切换：out-in 模式下两段动画是串行的，所以刻意压短（总时长 ≈ 260ms），
   否则每次导航都要"等动画"—— 在有了 KeepAlive 之后动画反而是主要延迟来源。 */
.page-leave-active {
  transition: opacity 0.09s linear;
}
.page-enter-active {
  transition: opacity 0.15s var(--ease-out), transform 0.15s var(--ease-out);
}
.page-enter-from {
  opacity: 0;
  transform: translateY(4px);
}
.page-leave-to {
  opacity: 0;
}
</style>
