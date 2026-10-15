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
/* 环境底纹：给数据面增加纵深（不拦截事件）。
   三种模式由 <html data-backdrop> 控制：
     grid  = 网格 + 顶部光晕（默认）
     plain = 只留顶部光晕
     none  = 完全纯色，最省 GPU
   ⚠️ 具体 background 值定义在 **src/styles/appearance.css**（全局，非 scoped）。
   原因：scoped 样式会被编译成 `.body[data-v-xxx]`，而 `:root[...] .body[data-v-xxx]`
   这种「祖先在模板外」的选择器在 scoped 下行为脆弱（Vue 会把属性加到复合选择器末尾，
   容易变成命不中的形态）。这里只保留布局属性，颜色/纹理交给全局层。 */
.body::before {
  content: '';
  position: absolute;
  inset: 0 0 auto 0;
  height: 380px;
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
/* 页面级级联入场：动效层 motion.css 提供 .m-stagger 的关键帧与 --i 延迟约定。
   作用在 `.content` 的直接子块上（页面根容器会把它自己的区块摊平上来），
   于是整页会"自上下依次浮现"，而不是一次性硬切。
   ⚠️ 只在**首次挂载**时播一次 —— 主页面都被 KeepAlive 缓存，切回来不会重播，
      否则每次导航都重新入场，反而变成噪音。 */
.content > * {
  animation: m-fade-up var(--dur-slow) var(--ease-out) both;
  animation-delay: calc(var(--i, 0) * var(--stagger-step));
}
.content > *:nth-child(1) { --i: 0; }
.content > *:nth-child(2) { --i: 1; }
.content > *:nth-child(3) { --i: 2; }
.content > *:nth-child(4) { --i: 3; }
.content > *:nth-child(5) { --i: 4; }
.content > *:nth-child(6) { --i: 5; }
.content > *:nth-child(7) { --i: 6; }
.content > *:nth-child(8) { --i: 7; }
.content > *:nth-child(n + 9) { --i: 8; }
/* 用户在设置里选了「动效：精简」时，整页入场一并停掉 */
:root[data-motion='reduced'] .content > * { animation: none; }
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
