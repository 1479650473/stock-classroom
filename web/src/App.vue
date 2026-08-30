<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useAppStore } from '@/stores/app'
import TitleBar from '@/components/TitleBar.vue'
import SideNav from '@/components/SideNav.vue'
import ToastHost from '@/components/ToastHost.vue'
import SearchPalette from '@/components/SearchPalette.vue'

const app = useAppStore()
const chatOpen = ref(false)
const searchOpen = ref(false)

onMounted(() => app.init())
</script>

<template>
  <div v-if="app.ready" class="shell">
    <TitleBar @open-search="searchOpen = true" @toggle-chat="chatOpen = !chatOpen" />
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
  flex: 1;
  display: flex;
  overflow: hidden;
}
.content {
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
