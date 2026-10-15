<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppPage from '@/components/ui/AppPage.vue'
import PageToolbar from '@/components/ui/PageToolbar.vue'
import SectionCard from '@/components/ui/SectionCard.vue'
import Agent from '@/views/Agent.vue'
import AgentOps from '@/views/AgentOps.vue'
import Trader from '@/views/v6/TraderHub.vue'

/**
 * AI 页（2026-10-16 梳理）
 *
 * ## 梳理前的问题
 * 1. **默认标签是个已停用的功能**：默认落在「AI 操盘手」，而该功能已被董事长停用
 *    （交易员 3 位，`enabled=1` 的 **0 位**）→ 每次点进 AI 先看到一个死功能。
 * 2. **标签名与功能不符**：原「自动操盘」装的是 `AgentOps`，而它其实是
 *    **按需分析工具**（信号扫描 / 个股深挖 / 组合重平衡），根本不是"自动"交易。
 *    这个名字会让人以为系统在自动下单 —— 在交易软件里这是**危险的误导**。
 * 3. **命名撞车**：「对话操盘」所载组件 `Agent.vue` 自身标题是「AI 操盘台」，
 *    与「AI 操盘手」（TraderHub）字面几乎一样，用户分不清哪个是哪个。
 *
 * ## 梳理后
 * | tab | 名称 | 本质 | 状态 |
 * | --- | --- | --- | --- |
 * | `chat`   | AI 操盘台 | **对话式**：自由调用软件工具（查行情/写策略/回测/盯盘/下单）| 在用 |
 * | `tools`  | AI 工具台 | **按需**分析：信号扫描 · 个股深挖 · 组合重平衡 | 在用 |
 * | `trader` | AI 操盘手 | **自主**多日交易：每位交易员独立账户/模型/记忆 | **已停用** |
 *
 * 排序即优先级：在用的放前面；停用的放最后并挂「已停用」角标
 * （仍可点进去查历史决策，停用 ≠ 不可访问）。
 *
 * ## 兼容
 * 旧的 `?tab=auto`（来自 `/agentops` 重定向）仍可访问 → 归一到 `tools`。
 * 旧 URL 的语义与新命名本来就一致，所以**路由表无需改动**。
 */
type Tab = 'chat' | 'tools' | 'trader'

const route = useRoute()
const router = useRouter()

const TABS = [
  { value: 'chat', label: 'AI 操盘台', icon: 'chat' },
  { value: 'tools', label: 'AI 工具台', icon: 'sparkles' },
  { value: 'trader', label: 'AI 操盘手', icon: 'agentops', badge: '已停用' },
]

/** 归一：新值 + 兼容旧 `auto`；未知值一律落到默认 `chat` */
function normalize(v: unknown): Tab {
  const s = String(v || '')
  if (s === 'tools' || s === 'auto') return 'tools'
  if (s === 'trader') return 'trader'
  return 'chat'
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
  <AppPage title="AI" subtitle="对话式操盘台 · 按需分析工具 · 自主交易员（已停用）">
    <SectionCard :padded="false">
      <div style="padding: 0 var(--sp-5)">
        <PageToolbar v-model="tab" :tabs="TABS" />
      </div>
      <div class="pane">
        <Agent v-if="tab === 'chat'" embedded />
        <AgentOps v-else-if="tab === 'tools'" embedded />
        <Trader v-else />
      </div>
    </SectionCard>
  </AppPage>
</template>

<style scoped>
.pane { padding: var(--sp-5); }
</style>
