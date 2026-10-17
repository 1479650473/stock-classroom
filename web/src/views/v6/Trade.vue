<script setup lang="ts">
import { computed, onActivated, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppPage from '@/components/ui/AppPage.vue'
import PageToolbar from '@/components/ui/PageToolbar.vue'
import SectionCard from '@/components/ui/SectionCard.vue'
import DataTable from '@/components/ui/DataTable.vue'
import type { DataColumn } from '@/components/ui/DataTable.vue'
import TradeSystems from '@/components/TradeSystems.vue'
import SimPanel from '@/components/SimPanel.vue'
import StrategyPicks from '@/components/StrategyPicks.vue'
import LiveAccount from '@/components/LiveAccount.vue'
import FormField from '@/components/ui/FormField.vue'
import Drawer from '@/components/ui/Drawer.vue'
import Icon from '@/components/Icon.vue'
import { useToastStore } from '@/stores/toast'
import {
  listAccounts, createAccount, resetAccount,
  getNavHistory, getPicks, runPicks,
} from '@/api'
import type { AccountSummary, PickItem } from '@/api'
import { useEChart, cssVar } from '@/composables/useEChart'
import { areaLineStyle, tooltipStyle } from '@/lib/chartTheme'
import { usePersistedRef } from '@/composables/usePersistedRef'

/**
 * 交易页（2026-10-16 合并「实盘」）
 *
 * ## 合并前的重复
 *   · **交易**（一级）＝ 通用模拟账户的 持仓/下单/订单/选股/模拟盘
 *   · **实盘**（一级）＝ 国信金太阳真实客户端 启动/解锁/读账户/下单/对账/快照
 *   两边在「持仓」「下单」「订单」三处职责重复，一边模拟一边真实，
 *   同级并存很容易点错。
 *
 * ## 合并后（董事长裁定）
 *   · **删掉模拟账户的「人工操作」**：`持仓` / `下单` / `订单` 三个 tab 移除。
 *     这套东西原本目的是"操作用来模拟"，现在实盘可用 → 模拟下单已无意义。
 *   · **实盘整页并入**为一个 tab（原一级「实盘」的全部功能）。
 *   · **模拟盘按新定位保留**：它已不是"动手练手"的地方，而是
 *     **策略自行驱动**的结果展示 —— 净值曲线 / 持仓明细 / 交易流水
 *     正是用来"看策略真实在干什么"的，因此**完整保留**（见 SimPanel，未改动）。
 *
 * ## 为什么删掉模拟持仓/订单不丢信息
 * 「模拟盘」tab 内本就有**持仓明细**与**交易流水**（按账户 + 按调仓日分组），
 * 同样来自模拟账户快照 —— 覆盖面够了，且带"哪个策略、哪次调仓"的上下文，比裸表更好读。
 */
type Tab = 'systems' | 'live' | 'picks' | 'sim'

const route = useRoute()
const router = useRouter()
const toast = useToastStore()

const TABS = [
  { value: 'systems', label: '体系总览', icon: 'layers' },
  { value: 'live', label: '实盘', icon: 'wallet' },
  { value: 'picks', label: '选股', icon: 'picks' },
  { value: 'sim', label: '模拟盘', icon: 'compare' },
]

const TAB_VALUES = TABS.map((t) => t.value) as Tab[]

/** 归一：新值 + 旧 URL 兼容 */
function normalizeTab(v: unknown): Tab {
  const s = String(v || '')
  if (TAB_VALUES.includes(s as Tab)) return s as Tab
  // 被移除的三个 tab 都是"模拟账户人工操作"，其信息现在在「模拟盘」里 → 落到 sim
  if (s === 'positions' || s === 'order' || s === 'orders') return 'sim'
  return 'systems'
}

const tab = ref<Tab>(normalizeTab(route.query.tab))

watch(tab, (v) => {
  if (route.query.tab !== v) router.replace({ query: { ...route.query, tab: v } })
})
watch(
  () => route.query.tab,
  (v) => {
    const n = normalizeTab(v)
    if (n !== tab.value) tab.value = n
  },
)

const SUBTITLES: Record<Tab, string> = {
  systems: '三个程序交易体系：固定策略（因子公式）· 外部 LLM 决策 · 本地预测模型',
  live: '实盘账户信息 · 总资产 / 可用 / 持仓盈亏 / 当日盈亏 / 持仓明细',
  picks: '多因子评分候选池（点「运行选股」重新扫描）',
  sim: '模拟账户 · 各策略净值曲线 · 持仓明细 · 交易流水（策略自行驱动）',
}

// ---------------- 账户（仅用于模拟盘查看 / 选股上下文） ----------------
const accounts = ref<AccountSummary[]>([])
const selectedId = usePersistedRef<number | null>('trade.accountId', null)
const nav = ref<number[]>([])
const advancedOpen = ref(false)
const accountBusy = ref(false)
const draft = ref({ newName: '', newCapital: 100000 })

const current = computed(() => accounts.value.find((a) => a.account_id === selectedId.value) || null)

const navEl = ref<HTMLElement | null>(null)
const { draw: drawNav } = useEChart(navEl, () => {
  const n = nav.value
  const start = n[0] || 0
  const idx = n.map((v) => (start ? +((v / start) * 100).toFixed(2) : 0))
  return {
    grid: { left: 56, right: 18, top: 18, bottom: 28 },
    tooltip: { trigger: 'axis', ...tooltipStyle() },
    xAxis: { type: 'category', data: idx.map((_, i) => i), axisLabel: { show: false }, axisLine: { lineStyle: { color: cssVar('--border') } } },
    yAxis: { type: 'value', scale: true, splitLine: { lineStyle: { color: cssVar('--border-soft') } } },
    series: [{ type: 'line', data: idx, ...areaLineStyle(cssVar('--gold'), 2, 0.3) }],
  }
})

async function loadAccounts() {
  try {
    accounts.value = await listAccounts()
    if (accounts.value.length) {
      if (!selectedId.value || !accounts.value.some((a) => a.account_id === selectedId.value)) {
        selectedId.value = accounts.value[0].account_id
      }
      await loadNav()
    }
  } catch { /* 后端未就绪时静默 */ }
}

async function loadNav() {
  if (!selectedId.value) { nav.value = []; return }
  try {
    const r = await getNavHistory(selectedId.value)
    nav.value = r.nav || []
    drawNav()
  } catch { nav.value = [] }
}

// ---------------- 选股 ----------------
const picks = ref<PickItem[]>([])
const picksStale = ref(false)
const picksRunning = ref(false)

const pickColumns: DataColumn[] = [
  { key: 'code', title: '代码', cellClass: 'mono' },
  { key: 'name', title: '名称' },
  { key: 'price', title: '现价', align: 'right', format: (r) => Number(r.price).toFixed(2) },
  { key: 'change_pct', title: '涨跌', align: 'right', sortable: true },
  { key: 'score', title: '评分', align: 'right', sortable: true, format: (r) => Number(r.score).toFixed(1) },
]

async function loadPicks() {
  try {
    const d = await getPicks(20)
    picks.value = d.items
    picksStale.value = d.stale
  } catch { /* 无缓存时静默 */ }
}

/** 运行选股：触发任务后轮询 pick 结果，直到 stale 消失（沿用原实现） */
async function rescanPicks() {
  picksRunning.value = true
  toast.info('开始扫描候选池…')
  try {
    await runPicks(true)
    let tries = 0
    const timer = setInterval(async () => {
      tries++
      try {
        const d = await getPicks(20)
        if (!d.stale || tries > 30) {
          clearInterval(timer)
          picks.value = d.items
          picksStale.value = d.stale
          picksRunning.value = false
          toast.success('选股已更新')
        }
      } catch { /* 轮询瞬断忽略 */ }
    }, 3000)
  } catch (e) {
    picksRunning.value = false
    toast.error('扫描失败：' + (e instanceof Error ? e.message : String(e)))
  }
}

// ---------------- 账户设置（只保留新建 / 重置） ----------------
async function doCreateAccount() {
  const name = draft.value.newName.trim()
  if (!name) { toast.error('请输入账户名'); return }
  accountBusy.value = true
  try {
    await createAccount(name, draft.value.newCapital)
    draft.value.newName = ''
    await loadAccounts()
    toast.success('账户已创建')
  } catch (e) {
    toast.error('创建失败：' + (e instanceof Error ? e.message : String(e)))
  } finally { accountBusy.value = false }
}

async function doResetAccount() {
  if (!selectedId.value) return
  if (!confirm('确定重置该账户？持仓与订单都会清空。')) return
  accountBusy.value = true
  try {
    await resetAccount(selectedId.value)
    await loadAccounts()
    toast.success('账户已重置')
  } catch (e) {
    toast.error('重置失败：' + (e instanceof Error ? e.message : String(e)))
  } finally { accountBusy.value = false }
}

onActivated(() => { if (tab.value === 'picks') void loadPicks() })
onMounted(async () => {
  await loadAccounts()
  if (tab.value === 'picks') await loadPicks()
})
watch(tab, (v) => { if (v === 'picks' && !picks.value.length) void loadPicks() })
watch(selectedId, () => { void loadNav() })
</script>

<template>
  <AppPage title="交易" :subtitle="SUBTITLES[tab]">
    <SectionCard :padded="false">
      <div style="padding: 0 var(--sp-5)">
        <PageToolbar v-model="tab" :tabs="TABS" advanced @advanced="advancedOpen = true">
          <template #extra>
            <button
              v-if="tab === 'picks'"
              class="ui-btn ui-btn--primary ui-btn--sm"
              :disabled="picksRunning"
              @click="rescanPicks"
            >
              <Icon :name="picksRunning ? 'refresh' : 'search'" :size="14" :class="{ spin: picksRunning }" />
              {{ picksRunning ? '扫描中…' : '运行选股' }}
            </button>
            <span v-if="tab === 'picks' && picksStale" class="ui-chip ui-chip--gold">缓存可刷新</span>
          </template>
        </PageToolbar>
      </div>

      <!-- 体系总览 -->
      <div v-if="tab === 'systems'" class="pane">
        <TradeSystems @go="(t) => (tab = normalizeTab(t))" />
      </div>

      <!-- 实盘：**只反馈账户信息**。
           2026-10-17 董事长定调：识屏/模拟输入那些工具都是**给 Agent 用的**，
           他本人直接操作券商客户端即可，不需要页面上的"一键启动/下单/读取"。
           工具面板已移到「设置 → Agent 自动化工具」，后端接口全部保留（Agent 仍在用）。 -->
      <div v-else-if="tab === 'live'" class="pane">
        <LiveAccount />

        <p class="live-note">
          <Icon name="info" :size="13" />
          <span>
            账户数据取自<b>策略侧每日核对记录</b>（盘前 09:35 / 盘后 15:10，见 AUTO_LOG），
            因此<b>不是逐笔实时</b>。要看实时明细请直接看券商客户端 ——
            本页面只做信息汇总，不代你操作下单。
          </span>
        </p>
      </div>

      <!-- 选股：默认展示**实盘策略（pali）真正的决策**（为策略服务）；
           软件自带的「全市场扫描」降为对照，放在下方。 -->
      <div v-else-if="tab === 'picks'" class="pane">
        <StrategyPicks />

        <details class="scan">
          <summary>
            <Icon name="search" :size="13" />
            软件自带的「全市场扫描」（多因子，<b>与实盘策略无关</b>）· 点开对照
          </summary>
          <div class="scan__body">
            <p class="scan__hint">
              这是软件自己跑的多因子扫描，<b>实盘不用它</b>。保留仅为对照参考。
            </p>
            <div class="scan__bar">
              <button class="ui-btn ui-btn--sm" :disabled="picksRunning" @click="rescanPicks">
                <Icon :name="picksRunning ? 'refresh' : 'search'" :size="13" :class="{ spin: picksRunning }" />
                {{ picksRunning ? '扫描中…' : '运行扫描' }}
              </button>
              <span v-if="picksStale" class="ui-chip ui-chip--gold">缓存可刷新</span>
            </div>
            <DataTable
              :columns="pickColumns"
              :rows="picks as unknown as Record<string, unknown>[]"
              compact
              row-key="code"
              storage-key="trade.picks"
              empty-title="还没有扫描结果"
              empty-desc="点「运行扫描」生成。"
            />
          </div>
        </details>
      </div>

      <!-- 模拟盘：策略自行驱动的结果（净值 / 持仓明细 / 交易流水） -->
      <div v-else class="pane">
        <SimPanel />
      </div>
    </SectionCard>

    <!-- 高级设置：只保留新建/重置（模拟账户的人工下单已移除） -->
    <Drawer v-model:open="advancedOpen" title="模拟账户设置" desc="这些账户由策略驱动；此处仅用于新建与重置">
      <div class="adv">
        <FormField label="新建账户">
          <div class="adv-row">
            <input v-model="draft.newName" class="ui-input" placeholder="账户名" />
            <button class="ui-btn ui-btn--primary" :disabled="accountBusy" @click="doCreateAccount">
              <Icon name="plus" :size="14" /> 创建
            </button>
          </div>
        </FormField>
        <FormField label="当前账户">
          <div class="adv-row">
            <span class="mono">{{ current?.name || '—' }}</span>
            <button class="ui-btn ui-btn--danger" :disabled="accountBusy || !selectedId" @click="doResetAccount">
              <Icon name="restore" :size="14" /> 重置账户
            </button>
          </div>
        </FormField>
      </div>
    </Drawer>
  </AppPage>
</template>

<style scoped>
.pane { padding: var(--sp-5); }
/* 嵌入式子页（实盘）：左右不再补内边距（它自带的卡片已有内边距），
   但要保留上/下的呼吸，否则内容会顶到 Tab 栏的底边框上。 */
.pane--bare { padding: var(--sp-5) 0; }
.adv { display: flex; flex-direction: column; gap: var(--sp-5); }
.adv-row { display: flex; align-items: center; gap: var(--sp-3); }
.adv-row .ui-input { flex: 1; }
.spin { animation: m-spin 0.9s linear infinite; }

/* 「全市场扫描」折叠区：实盘策略是主角，它是配角，所以默认收起 */
.scan { margin-top: var(--sp-5); }
.scan > summary {
  display: flex; align-items: center; gap: 6px;
  padding: 9px 12px; cursor: pointer; user-select: none;
  border: 1px solid var(--border-soft); border-radius: var(--radius-md);
  background: var(--bg-panel); color: var(--text-sub); font-size: var(--fs-sm);
}
.scan > summary:hover { color: var(--text); border-color: var(--border-strong); }
.scan__body { padding-top: var(--sp-4); display: flex; flex-direction: column; gap: var(--sp-3); }
.scan__hint { margin: 0; font-size: var(--fs-sm); color: var(--text-faint); }
.scan__bar { display: flex; align-items: center; gap: var(--sp-3); }
</style>
