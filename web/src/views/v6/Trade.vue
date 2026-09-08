<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppPage from '@/components/ui/AppPage.vue'
import PageToolbar from '@/components/ui/PageToolbar.vue'
import SectionCard from '@/components/ui/SectionCard.vue'
import StatTile from '@/components/ui/StatTile.vue'
import DataTable from '@/components/ui/DataTable.vue'
import type { DataColumn } from '@/components/ui/DataTable.vue'
import SegmentedControl from '@/components/ui/SegmentedControl.vue'
import FormField from '@/components/ui/FormField.vue'
import Drawer from '@/components/ui/Drawer.vue'
import EmptyGuide from '@/components/ui/EmptyGuide.vue'
import Icon from '@/components/Icon.vue'
import { useToastStore } from '@/stores/toast'
import {
  listAccounts, getPositions, getOrders, placeOrder, cancelOrder, refreshPrices,
  getNavHistory, getPicks, runPicks,
} from '@/api'
import type { AccountSummary, Position, Order, PickItem } from '@/api'
import { useEChart, cssVar } from '@/composables/useEChart'

type Tab = 'positions' | 'order' | 'orders' | 'picks'

const route = useRoute()
const router = useRouter()
const toast = useToastStore()

const TABS = [
  { value: 'positions', label: '持仓', icon: 'holdings' },
  { value: 'order', label: '下单', icon: 'trade' },
  { value: 'orders', label: '订单', icon: 'log' },
  { value: 'picks', label: '选股', icon: 'picks' },
]

const tab = ref<Tab>(normalizeTab(route.query.tab))
const accounts = ref<AccountSummary[]>([])
const selectedId = ref<number | null>(null)
const loading = ref(true)
const loadError = ref('')

const positions = ref<Position[]>([])
const orders = ref<Order[]>([])
const picks = ref<PickItem[]>([])
const picksStale = ref(false)
const picksRunning = ref(false)
const nav = ref<number[]>([])
const navEl = ref<HTMLElement | null>(null)
const advancedOpen = ref(false)

const form = ref({
  side: 'buy' as 'buy' | 'sell',
  code: '',
  name: '',
  order_type: 'market' as 'market' | 'limit',
  price: 0,
  qty: 100,
})
const submitting = ref(false)

const currentAccount = computed(() =>
  accounts.value.find((a) => a.account_id === selectedId.value) ?? null,
)
const positionRows = computed(() => positions.value as unknown as Record<string, unknown>[])
const orderRows = computed(() => orders.value as unknown as Record<string, unknown>[])
const pickRows = computed(() => picks.value as unknown as Record<string, unknown>[])
const posMarketValue = computed(() => positions.value.reduce((s, p) => s + p.market_value, 0))
const posFloatPnl = computed(() => positions.value.reduce((s, p) => s + p.float_pnl, 0))

function normalizeTab(v: unknown): Tab {
  const s = String(v || '')
  return (['positions', 'order', 'orders', 'picks'] as const).includes(s as Tab)
    ? (s as Tab)
    : 'positions'
}

watch(tab, (v) => {
  const q = { ...route.query, tab: v }
  if (route.query.tab !== v) router.replace({ query: q })
})

watch(
  () => route.query,
  (q) => {
    const next = normalizeTab(q.tab)
    if (next !== tab.value) tab.value = next
    if (q.code) {
      form.value.code = String(q.code)
      form.value.name = String(q.name || '')
      form.value.side = q.side === 'sell' ? 'sell' : 'buy'
      form.value.qty = Number(q.qty) || 100
      if (next !== 'order') tab.value = 'order'
    }
  },
)

const { draw: drawNav } = useEChart(navEl, () => {
  const n = nav.value
  const start = n[0] || 0
  const idx = n.map((v) => (start ? +((v / start) * 100).toFixed(2) : 0))
  return {
    grid: { left: 56, right: 18, top: 18, bottom: 28 },
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: idx.map((_, i) => i), axisLabel: { show: false }, axisLine: { lineStyle: { color: cssVar('--border') } } },
    yAxis: { type: 'value', scale: true, splitLine: { lineStyle: { color: cssVar('--border-soft') } } },
    series: [{
      type: 'line', data: idx, smooth: true, showSymbol: false,
      lineStyle: { color: cssVar('--gold'), width: 2 },
      areaStyle: { color: cssVar('--gold-dim') },
    }],
  }
})

async function loadAccounts() {
  loading.value = true
  loadError.value = ''
  try {
    accounts.value = await listAccounts()
    if (accounts.value.length) {
      if (!selectedId.value || !accounts.value.some((a) => a.account_id === selectedId.value)) {
        selectedId.value = accounts.value[0].account_id
      }
      await refreshAccountData()
    }
  } catch (e) {
    loadError.value = e instanceof Error ? e.message : '账户加载失败'
  } finally {
    loading.value = false
  }
}

async function refreshAccountData() {
  if (!selectedId.value) return
  await Promise.all([loadPositions(), loadOrders(), loadNav()])
}

async function loadPositions() {
  if (!selectedId.value) return
  try { positions.value = await getPositions(selectedId.value) }
  catch (e) { toast.error('持仓加载失败：' + msg(e)) }
}

async function loadOrders() {
  if (!selectedId.value) return
  try { orders.value = await getOrders(selectedId.value) }
  catch (e) { toast.error('订单加载失败：' + msg(e)) }
}

async function loadNav() {
  if (!selectedId.value) return
  try {
    const r = await getNavHistory(selectedId.value)
    nav.value = r.nav || []
    navEl.value && drawNav()
  } catch { nav.value = [] }
}

async function loadPicks() {
  try {
    const d = await getPicks(20)
    picks.value = d.items
    picksStale.value = d.stale
  } catch (e) { toast.error('选股加载失败：' + msg(e)) }
}

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
    toast.error('扫描失败：' + msg(e))
    picksRunning.value = false
  }
}

async function submitOrder() {
  if (!selectedId.value) { toast.error('请先选择账户'); return }
  if (!form.value.code) { toast.error('请输入股票代码'); return }
  if (!form.value.qty || form.value.qty <= 0) { toast.error('请输入有效数量'); return }
  submitting.value = true
  try {
    await placeOrder({
      account_id: selectedId.value,
      code: form.value.code,
      name: form.value.name || undefined,
      side: form.value.side,
      order_type: form.value.order_type,
      price: form.value.order_type === 'limit' ? form.value.price : undefined,
      qty: form.value.qty,
    })
    toast.success(`${form.value.side === 'buy' ? '买入' : '卖出'}委托已提交`)
    await Promise.all([loadOrders(), loadPositions()])
    tab.value = 'orders'
  } catch (e) {
    toast.error('委托失败：' + msg(e))
  } finally {
    submitting.value = false
  }
}

async function buyPick(p: PickItem) {
  if (!selectedId.value) { toast.error('请先选择账户'); return }
  try {
    await placeOrder({
      account_id: selectedId.value,
      code: p.code,
      name: p.name,
      side: 'buy',
      order_type: 'limit',
      price: p.price,
      qty: 100,
    })
    toast.success(`已提交买入 ${p.name} (${p.code}) ×100`)
    await loadOrders()
  } catch (e) {
    toast.error('买入失败：' + msg(e))
  }
}

function sellPosition(p: Position) {
  form.value.code = p.code
  form.value.name = p.name
  form.value.side = 'sell'
  form.value.order_type = 'market'
  form.value.qty = p.qty
  tab.value = 'order'
}

async function handleCancel(id: number) {
  try {
    await cancelOrder(id)
    toast.success('撤单成功')
    await loadOrders()
  } catch (e) { toast.error('撤单失败：' + msg(e)) }
}

async function handleRefresh() {
  if (!selectedId.value) return
  try {
    await refreshPrices(selectedId.value)
    toast.success('价格已刷新')
    await refreshAccountData()
  } catch (e) { toast.error('刷新价格失败：' + msg(e)) }
}

function msg(e: unknown) { return e instanceof Error ? e.message : String(e) }

function fmtMoney(v: number) {
  if (Math.abs(v) >= 1e8) return (v / 1e8).toFixed(2) + '亿'
  if (Math.abs(v) >= 1e4) return (v / 1e4).toFixed(2) + '万'
  return v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}
function fmtPct(v: number) { return (v >= 0 ? '+' : '') + v.toFixed(2) + '%' }

const positionColumns: DataColumn[] = [
  { key: 'code', title: '代码', cellClass: 'mono' },
  { key: 'name', title: '名称' },
  { key: 'qty', title: '持仓', align: 'right', format: (r) => Number(r.qty).toLocaleString() },
  { key: 'cost_price', title: '成本', align: 'right', format: (r) => Number(r.cost_price).toFixed(2) },
  { key: 'current_price', title: '现价', align: 'right', format: (r) => Number(r.current_price).toFixed(2) },
  { key: 'market_value', title: '市值', align: 'right', format: (r) => fmtMoney(Number(r.market_value)) },
  { key: 'float_pnl', title: '盈亏', align: 'right', sortable: true },
  { key: 'pnl_pct', title: '盈亏%', align: 'right' },
  { key: 'last_buy_date', title: '买入日期' },
]

const orderColumns: DataColumn[] = [
  { key: 'created_at', title: '时间', format: (r) => String(r.created_at || '').slice(5, 16) },
  { key: 'side', title: '方向' },
  { key: 'code', title: '代码', cellClass: 'mono' },
  { key: 'name', title: '名称' },
  { key: 'price', title: '价格', align: 'right' },
  { key: 'qty', title: '数量', align: 'right', format: (r) => Number(r.qty).toLocaleString() },
  { key: 'status', title: '状态' },
]

const pickColumns: DataColumn[] = [
  { key: 'code', title: '代码', cellClass: 'mono' },
  { key: 'name', title: '名称' },
  { key: 'price', title: '现价', align: 'right', format: (r) => Number(r.price).toFixed(2) },
  { key: 'change_pct', title: '涨跌', align: 'right', sortable: true },
  { key: 'score', title: '评分', align: 'right', sortable: true, format: (r) => Number(r.score).toFixed(1) },
]

onMounted(async () => {
  await loadAccounts()
  if (tab.value === 'picks') await loadPicks()
})

watch(tab, async (v) => {
  if (v === 'picks' && !picks.value.length) await loadPicks()
})
</script>

<template>
  <AppPage title="交易" subtitle="持仓 · 下单 · 订单 · 选股，一处完成">
    <template #actions>
      <select
        v-if="accounts.length > 1"
        v-model="selectedId"
        class="ui-select"
        style="width: 140px"
        @change="refreshAccountData"
      >
        <option v-for="a in accounts" :key="a.account_id" :value="a.account_id">{{ a.name }}</option>
      </select>
      <button class="ui-btn" :disabled="!selectedId" @click="handleRefresh">
        <Icon name="refresh" :size="14" /><span>刷新价格</span>
      </button>
      <button class="ui-btn ui-btn--primary" @click="tab = 'order'">
        <Icon name="plus" :size="14" /><span>下单</span>
      </button>
    </template>

    <EmptyGuide
      v-if="!loading && !accounts.length"
      icon="wallet"
      title="还没有模拟账户"
      desc="先创建一个账户，就可以开始模拟交易了。"
    >
      <template #action>
        <button class="ui-btn ui-btn--primary" @click="advancedOpen = true">账户设置</button>
      </template>
    </EmptyGuide>

    <template v-else>
      <div v-if="currentAccount" class="metrics">
        <StatTile label="总资产" :value="fmtMoney(currentAccount.total_assets)" icon="wallet" />
        <StatTile
          label="总盈亏"
          :value="fmtMoney(currentAccount.total_profit)"
          :trend="currentAccount.total_profit >= 0 ? 'up' : 'down'"
          :hint="fmtPct(currentAccount.total_profit_pct)"
          :hint-trend="currentAccount.total_profit >= 0 ? 'up' : 'down'"
        />
        <StatTile label="持仓市值" :value="fmtMoney(posMarketValue)" :hint="`${positions.length} 只`" />
        <StatTile
          label="浮动盈亏"
          :value="fmtMoney(posFloatPnl)"
          :trend="posFloatPnl >= 0 ? 'up' : 'down'"
        />
        <StatTile label="可用余额" :value="fmtMoney(currentAccount.balance)" />
      </div>

      <SectionCard :padded="false">
        <div style="padding: 0 var(--sp-5)">
          <PageToolbar v-model="tab" :tabs="TABS" advanced @advanced="advancedOpen = true">
            <template #extra>
              <span v-if="tab === 'orders'" class="ui-chip">{{ orders.length }} 笔</span>
              <span v-if="tab === 'picks' && picksStale" class="ui-chip ui-chip--gold">缓存可刷新</span>
            </template>
          </PageToolbar>
        </div>

        <!-- 持仓 -->
        <div v-if="tab === 'positions'" class="pane">
          <DataTable
            :columns="positionColumns"
            :rows="positionRows"
            row-key="id"
            empty-title="当前空仓"
            empty-desc="到「选股」挑一只，或在「下单」里手动买入。"
            :page-size="20"
          >
            <template #cell-float_pnl="{ row }">
              <span :class="Number(row.float_pnl) >= 0 ? 'up' : 'down'">{{ fmtMoney(Number(row.float_pnl)) }}</span>
            </template>
            <template #cell-pnl_pct="{ row }">
              <span :class="Number(row.float_pnl) >= 0 ? 'up' : 'down'">
                {{ fmtPct(Number(row.cost_price) ? ((Number(row.current_price) - Number(row.cost_price)) / Number(row.cost_price)) * 100 : 0) }}
              </span>
            </template>
            <template #actions="{ row }">
              <button class="ui-btn ui-btn--sm" @click="sellPosition(row as unknown as Position)">卖出</button>
            </template>
          </DataTable>
        </div>

        <!-- 下单 -->
        <div v-else-if="tab === 'order'" class="pane">
          <div class="order-form">
            <FormField label="方向">
              <SegmentedControl
                v-model="form.side"
                block
                :options="[{ value: 'buy', label: '买入' }, { value: 'sell', label: '卖出' }]"
              />
            </FormField>
            <FormField label="股票代码" required>
              <input v-model="form.code" class="ui-input num" placeholder="600519" maxlength="6" />
            </FormField>
            <FormField label="名称">
              <input v-model="form.name" class="ui-input" placeholder="可选" />
            </FormField>
            <FormField label="委托类型">
              <select v-model="form.order_type" class="ui-select">
                <option value="market">市价</option>
                <option value="limit">限价</option>
              </select>
            </FormField>
            <FormField v-if="form.order_type === 'limit'" label="委托价">
              <input v-model.number="form.price" type="number" step="0.01" class="ui-input num" />
            </FormField>
            <FormField label="数量（股）">
              <input v-model.number="form.qty" type="number" step="100" min="100" class="ui-input num" />
            </FormField>
            <div class="order-form__submit">
              <button
                class="ui-btn ui-btn--primary"
                :disabled="submitting"
                @click="submitOrder"
              >
                {{ submitting ? '提交中…' : form.side === 'buy' ? '确认买入' : '确认卖出' }}
              </button>
            </div>
          </div>
        </div>

        <!-- 订单 -->
        <div v-else-if="tab === 'orders'" class="pane">
          <DataTable
            :columns="orderColumns"
            :rows="orderRows"
            row-key="id"
            empty-title="暂无订单"
            empty-desc="下单后会在这里显示，未成交的可撤单。"
            :page-size="20"
          >
            <template #cell-side="{ row }">
              <span class="ui-chip" :class="row.side === 'buy' ? 'ui-chip--up' : 'ui-chip--down'">
                {{ row.side === 'buy' ? '买入' : '卖出' }}
              </span>
            </template>
            <template #cell-price="{ row }">
              {{ (Number(row.filled_price) || Number(row.price) || 0).toFixed(2) }}
            </template>
            <template #cell-status="{ row }">
              <span class="ui-chip" :class="row.status === 'filled' ? 'ui-chip--down' : row.status === 'pending' ? 'ui-chip--gold' : ''">
                {{ row.status === 'filled' ? '已成交' : row.status === 'pending' ? '挂单中' : row.status === 'cancelled' ? '已撤单' : row.status }}
              </span>
            </template>
            <template #actions="{ row }">
              <button
                v-if="row.status === 'pending'"
                class="ui-btn ui-btn--sm ui-btn--danger"
                @click="handleCancel(Number(row.id))"
              >
                撤单
              </button>
            </template>
          </DataTable>
        </div>

        <!-- 选股 -->
        <div v-else class="pane">
          <DataTable
            :columns="pickColumns"
            :rows="pickRows"
            row-key="code"
            :loading="picksRunning"
            empty-title="暂无选股结果"
            empty-desc="点击「重新扫描」运行多因子评分，生成 Top 20 候选。"
            :page-size="20"
          >
            <template #cell-change_pct="{ row }">
              <span :class="Number(row.change_pct) >= 0 ? 'up' : 'down'">
                {{ fmtPct(Number(row.change_pct)) }}
              </span>
            </template>
            <template #cell-score="{ row }">
              <span class="gold">{{ Number(row.score).toFixed(1) }}</span>
            </template>
            <template #actions="{ row }">
              <button class="ui-btn ui-btn--sm" @click="buyPick(row as unknown as PickItem)">买入</button>
            </template>
            <template #empty-action>
              <button class="ui-btn ui-btn--primary" :disabled="picksRunning" @click="rescanPicks">
                {{ picksRunning ? '扫描中…' : '重新扫描' }}
              </button>
            </template>
          </DataTable>
        </div>
      </SectionCard>

      <!-- 净值曲线 -->
      <SectionCard v-if="tab === 'positions' && nav.length > 1" title="账户净值曲线">
        <div ref="navEl" class="nav-chart" />
      </SectionCard>
    </template>

    <Drawer v-model:open="advancedOpen" title="账户设置" desc="创建、重命名或重置模拟账户">
      <EmptyGuide icon="settings" title="账户管理" desc="账户创建/重置等高级操作将在此处提供。" />
    </Drawer>
  </AppPage>
</template>

<style scoped>
.metrics {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: var(--sp-4);
  padding: var(--sp-5);
  background: var(--bg-raised);
  border: 1px solid var(--border-soft);
  border-radius: var(--radius-lg);
}
.pane { padding: var(--sp-2) var(--sp-5) var(--sp-5); }
.order-form {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: var(--sp-4);
  max-width: 760px;
  padding-top: var(--sp-4);
}
.order-form__submit { display: flex; align-items: flex-end; }
.order-form__submit .ui-btn { width: 100%; }
.nav-chart { height: 260px; }
.mono { font-family: var(--font-mono); }
.gold { color: var(--gold); font-weight: 600; }
</style>
