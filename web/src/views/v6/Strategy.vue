<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppPage from '@/components/ui/AppPage.vue'
import PageToolbar from '@/components/ui/PageToolbar.vue'
import SectionCard from '@/components/ui/SectionCard.vue'
import StatTile from '@/components/ui/StatTile.vue'
import LoadingBlock from '@/components/ui/LoadingBlock.vue'
import EmptyGuide from '@/components/ui/EmptyGuide.vue'
import Icon from '@/components/Icon.vue'
import Research from '@/views/Research.vue'
import Optimize from '@/views/Optimize.vue'
import Replay from '@/views/Replay.vue'
import AlphaMine from '@/components/AlphaMine.vue'
import { getRegime } from '@/api'
import type { RegimeData } from '@/api'

type Tab = 'env' | 'research' | 'optimize' | 'replay' | 'alpha'

const route = useRoute()
const router = useRouter()

const TABS = [
  { value: 'env', label: '环境', icon: 'market' },
  { value: 'research', label: '研究 / 回测', icon: 'research' },
  { value: 'optimize', label: '策略进化', icon: 'trending' },
  { value: 'replay', label: '策略回放', icon: 'play' },
  { value: 'alpha', label: '因子挖掘', icon: 'sparkles' },
]

const tab = ref<Tab>(normalize(route.query.tab))
const regime = ref<RegimeData | null>(null)
const loading = ref(true)
const error = ref('')

function normalize(v: unknown): Tab {
  const s = String(v || '')
  return (['env', 'research', 'optimize', 'replay', 'alpha'] as const).includes(s as Tab) ? (s as Tab) : 'env'
}

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

async function loadRegime() {
  loading.value = !regime.value
  error.value = ''
  try {
    regime.value = await getRegime()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '环境数据加载失败'
  } finally {
    loading.value = false
  }
}

onMounted(loadRegime)

function regimeTone(r: string): 'up' | 'down' | 'neutral' {
  if (r === 'bull') return 'up'
  if (r === 'bear') return 'down'
  return 'neutral'
}

function scoreEntries(s: Record<string, unknown> | undefined): { k: string; v: string }[] {
  if (!s) return []
  return Object.entries(s)
    .filter(([, v]) => v != null && typeof v !== 'object')
    .map(([k, v]) => ({ k, v: typeof v === 'number' ? fmtMetric(v) : String(v) }))
}

function fmtMetric(v: number): string {
  const n = Math.abs(v) < 0.005 ? 0 : v
  return Number.isInteger(n) ? String(n) : n.toFixed(2)
}
</script>

<template>
  <AppPage title="策略" subtitle="市场环境 · 研究回测 · 策略进化 · 逐日回放">
    <template #actions>
      <button class="ui-btn" @click="tab = 'research'">
        <Icon name="backtest" :size="14" /><span>去回测</span>
      </button>
    </template>

    <SectionCard :padded="false">
      <div style="padding: 0 var(--sp-5)">
        <PageToolbar v-model="tab" :tabs="TABS" />
      </div>

      <!-- 环境 -->
      <div v-if="tab === 'env'" class="pane">
        <LoadingBlock v-if="loading && !regime" :rows="4" />
        <EmptyGuide v-else-if="error && !regime" icon="alert" title="环境数据加载失败" :desc="error">
          <template #action><button class="ui-btn" @click="loadRegime">重试</button></template>
        </EmptyGuide>
        <template v-else-if="regime">
          <div class="env-hero">
            <div class="env-hero__label">当前市场环境</div>
            <div class="env-hero__value" :class="regimeTone(regime.regime)">
              {{ regime.regime_cn }}
            </div>
            <div class="env-hero__suggest">
              推荐策略：<span class="gold">{{ regime.suggest_strategy }}</span>
            </div>
          </div>

          <div class="metrics">
            <StatTile
              v-for="item in scoreEntries(regime.score).slice(0, 4)"
              :key="item.k"
              :label="item.k"
              :value="item.v"
            />
            <StatTile
              v-for="item in scoreEntries(regime.sys_risk).slice(0, 2)"
              :key="'risk-' + item.k"
              :label="'系统风险 · ' + item.k"
              :value="item.v"
            />
          </div>

          <p class="as-of faint">数据时间：{{ regime.as_of }}</p>
        </template>
      </div>

      <!-- 研究 / 回测 -->
      <div v-else-if="tab === 'research'" class="pane">
        <Research embedded />
      </div>

      <!-- 进化 -->
      <div v-else-if="tab === 'optimize'" class="pane">
        <Optimize embedded />
      </div>

      <!-- 回放 -->
      <div v-else-if="tab === 'replay'" class="pane">
        <Replay embedded />
      </div>

      <!-- 因子挖掘 -->
      <div v-else class="pane">
        <AlphaMine />
      </div>
    </SectionCard>
  </AppPage>
</template>

<style scoped>
.pane { padding: var(--sp-5); }
.env-hero {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: var(--sp-5);
  margin-bottom: var(--sp-4);
  background: var(--bg);
  border: 1px solid var(--border-soft);
  border-radius: var(--radius-lg);
}
.env-hero__label { font-size: var(--fs-sm); color: var(--text-sub); }
.env-hero__value { font-size: var(--fs-hero); font-weight: 700; line-height: 1.1; }
.env-hero__suggest { font-size: var(--fs-md); color: var(--text-sub); }
/* .metrics 已收敛到全局样式（styles/base.css） */
.gold { color: var(--gold); font-weight: 600; }
.as-of { margin: var(--sp-4) 0 0; font-size: var(--fs-xs); }
</style>
