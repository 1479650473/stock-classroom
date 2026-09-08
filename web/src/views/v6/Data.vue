<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppPage from '@/components/ui/AppPage.vue'
import PageToolbar from '@/components/ui/PageToolbar.vue'
import SectionCard from '@/components/ui/SectionCard.vue'
import Pipeline from '@/views/Pipeline.vue'
import DataCenter from '@/views/DataCenter.vue'
import Trainer from '@/views/Trainer.vue'

type Tab = 'pipeline' | 'db' | 'trainer'

const route = useRoute()
const router = useRouter()

const TABS = [
  { value: 'pipeline', label: '数据管道', icon: 'pipeline' },
  { value: 'db', label: '数据库', icon: 'database' },
  { value: 'trainer', label: 'K线训练', icon: 'trainer' },
]

function normalize(v: unknown): Tab {
  const s = String(v || '')
  return (['pipeline', 'db', 'trainer'] as const).includes(s as Tab) ? (s as Tab) : 'pipeline'
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
  <AppPage title="数据" subtitle="数据管道 · 数据库状态 · K线训练模拟器">
    <SectionCard :padded="false">
      <div style="padding: 0 var(--sp-5)">
        <PageToolbar v-model="tab" :tabs="TABS" />
      </div>
      <div class="pane">
        <Pipeline v-if="tab === 'pipeline'" embedded />
        <DataCenter v-else-if="tab === 'db'" embedded />
        <Trainer v-else embedded />
      </div>
    </SectionCard>
  </AppPage>
</template>

<style scoped>
.pane { padding: var(--sp-5); }
</style>
