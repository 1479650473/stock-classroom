<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppPage from '@/components/ui/AppPage.vue'
import PageToolbar from '@/components/ui/PageToolbar.vue'
import SectionCard from '@/components/ui/SectionCard.vue'
import Agent from '@/views/Agent.vue'
import AgentOps from '@/views/AgentOps.vue'

type Tab = 'chat' | 'auto'

const route = useRoute()
const router = useRouter()

const TABS = [
  { value: 'chat', label: '对话操盘', icon: 'chat' },
  { value: 'auto', label: '自动操盘', icon: 'agentops' },
]

const tab = ref<Tab>(route.query.tab === 'auto' ? 'auto' : 'chat')

watch(tab, (v) => {
  if (route.query.tab !== v) router.replace({ query: { ...route.query, tab: v } })
})
watch(
  () => route.query.tab,
  (v) => {
    const n = v === 'auto' ? 'auto' : 'chat'
    if (n !== tab.value) tab.value = n
  },
)
</script>

<template>
  <AppPage title="AI" subtitle="对话操盘 · 自动操盘，让 AI 直接调用软件工具">
    <SectionCard :padded="false">
      <div style="padding: 0 var(--sp-5)">
        <PageToolbar v-model="tab" :tabs="TABS" />
      </div>
      <div class="pane">
        <Agent v-if="tab === 'chat'" embedded />
        <AgentOps v-else embedded />
      </div>
    </SectionCard>
  </AppPage>
</template>

<style scoped>
.pane { padding: var(--sp-5); }
</style>
