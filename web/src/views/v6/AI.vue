<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppPage from '@/components/ui/AppPage.vue'
import PageToolbar from '@/components/ui/PageToolbar.vue'
import SectionCard from '@/components/ui/SectionCard.vue'
import Agent from '@/views/Agent.vue'
import AgentOps from '@/views/AgentOps.vue'
import Trader from '@/views/v6/Trader.vue'

type Tab = 'trader' | 'chat' | 'auto'

const route = useRoute()
const router = useRouter()

const TABS = [
  { value: 'trader', label: 'AI 操盘手', icon: 'agentops' },
  { value: 'chat', label: '对话操盘', icon: 'chat' },
  { value: 'auto', label: '自动操盘', icon: 'sparkles' },
]

function normalize(v: unknown): Tab {
  return v === 'chat' || v === 'auto' ? v : 'trader'
}

const tab = ref<Tab>(normalize(route.query.tab))

watch(tab, (v) => {
  if (route.query.tab !== v) router.replace({ query: { ...route.query, tab: v } })
})
watch(
  () => route.query.tab,
  (v) => {
    const n = normalize(v)
    if (n !== tab.value) tab.value = n
  },
)
</script>

<template>
  <AppPage title="AI" subtitle="AI 操盘手长期自主交易 · 对话操盘 · 工具自动操盘">
    <SectionCard :padded="false">
      <div style="padding: 0 var(--sp-5)">
        <PageToolbar v-model="tab" :tabs="TABS" />
      </div>
      <div class="pane">
        <Trader v-if="tab === 'trader'" />
        <Agent v-else-if="tab === 'chat'" embedded />
        <AgentOps v-else embedded />
      </div>
    </SectionCard>
  </AppPage>
</template>

<style scoped>
.pane { padding: var(--sp-5); }
</style>
