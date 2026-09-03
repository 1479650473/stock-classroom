<script setup lang="ts">
import { onMounted, ref } from 'vue'
import PageHeader from '@/components/PageHeader.vue'
import Card from '@/components/Card.vue'
import StatCard from '@/components/StatCard.vue'
import EmptyState from '@/components/EmptyState.vue'
import Skeleton from '@/components/Skeleton.vue'
import Icon from '@/components/Icon.vue'
import { useToastStore } from '@/stores/toast'
import { listAccounts, getOrders, placeOrder, cancelOrder, refreshPrices } from '@/api'
import type { AccountSummary, Order } from '@/api'

const toast = useToastStore()
const accounts = ref<AccountSummary[]>([])
const selectedId = ref<number | null>(null)
const orders = ref<Order[]>([])
const loading = ref(true)
const submitting = ref(false)
const loadError = ref('')

const form = ref({
  side: 'buy' as 'buy' | 'sell',
  code: '',
  name: '',
  order_type: 'market',
  price: 0,
  qty: 100,
})

async function loadAccounts() {
  loading.value = true
  loadError.value = ''
  try {
    accounts.value = await listAccounts()
    if (accounts.value.length) {
      if (!selectedId.value || !accounts.value.some(a => a.account_id === selectedId.value)) {
        selectedId.value = accounts.value[0].account_id
      }
      await loadOrders()
    }
  } catch (e) {
    loadError.value = e instanceof Error ? e.message : '账户加载失败'
  } finally { loading.value = false }
}
onMounted(loadAccounts)

async function loadOrders() {
  if (!selectedId.value) return
  loading.value = true
  try { orders.value = await getOrders(selectedId.value) }
  catch (e) { toast.error('订单加载失败：' + (e instanceof Error ? e.message : String(e))) }
  finally { loading.value = false }
}

async function submitOrder() {
  if (!selectedId.value || !form.value.code) { toast.error('请输入股票代码'); return }
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
    form.value.code = ''
    form.value.name = ''
    await loadOrders()
  } catch (e: unknown) {
    toast.error('委托失败：' + (e instanceof Error ? e.message : String(e)))
  } finally { submitting.value = false }
}

async function handleCancel(id: number) {
  try { await cancelOrder(id); toast.success('撤单成功'); await loadOrders() }
  catch (e: unknown) { toast.error('撤单失败：' + (e instanceof Error ? e.message : String(e))) }
}

async function handleRefresh() {
  if (!selectedId.value) return
  try {
    await refreshPrices(selectedId.value)
    toast.success('价格已刷新')
    await loadOrders()
  } catch (e) {
    toast.error('刷新价格失败：' + (e instanceof Error ? e.message : String(e)))
  }
}

function fmtMoney(v: number) {
  if (Math.abs(v) >= 1e4) return (v / 1e4).toFixed(2) + '万'
  return v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}
</script>

<template>
  <div>
    <PageHeader title="交易" subtitle="模拟下单与订单管理">
      <template #right>
        <select v-if="accounts.length > 1" v-model="selectedId" class="sel" @change="loadOrders">
          <option v-for="a in accounts" :key="a.account_id" :value="a.account_id">{{ a.name }}</option>
        </select>
        <button class="btn-sm" @click="handleRefresh" title="刷新价格">
          <Icon name="refresh" :size="14" />
        </button>
      </template>
    </PageHeader>

    <Skeleton v-if="loading && !accounts.length" />
    <EmptyState v-if="loadError && !accounts.length" :message="loadError">
      <template #action>
        <button class="btn-sm retry" @click="loadAccounts">重试</button>
      </template>
    </EmptyState>
    <EmptyState v-if="!loading && !loadError && !accounts.length" message="暂无账户，请到设置或持仓页创建" />

    <template v-if="accounts.length && selectedId">
      <!-- account stats -->
      <div class="stats">
        <template v-for="a in accounts.filter(x => x.account_id === selectedId)" :key="a.account_id">
          <StatCard label="总资产" :value="fmtMoney(a.total_assets)" icon="wallet" />
          <StatCard label="盈亏" :value="fmtMoney(a.total_profit)" :trend="a.total_profit >= 0 ? 'up' : 'down'" :trend-value="(a.total_profit_pct >= 0 ? '+' : '') + a.total_profit_pct.toFixed(2) + '%'" />
          <StatCard label="可用余额" :value="fmtMoney(a.balance)" />
          <StatCard label="挂单" :value="String(a.pending_orders)" icon="alert" />
        </template>
      </div>

      <!-- order form -->
      <Card class="mt">
        <template #header><span class="card-title">下单</span></template>
        <div class="form">
          <div class="form-row">
            <div class="field">
              <label>方向</label>
              <div class="side-toggle">
                <button :class="['side-btn buy', { active: form.side === 'buy' }]" @click="form.side = 'buy'">买入</button>
                <button :class="['side-btn sell', { active: form.side === 'sell' }]" @click="form.side = 'sell'">卖出</button>
              </div>
            </div>
            <div class="field">
              <label>代码</label>
              <input v-model="form.code" class="inp code-inp" placeholder="600519" maxlength="6" />
            </div>
            <div class="field">
              <label>名称</label>
              <input v-model="form.name" class="inp" placeholder="可选" />
            </div>
            <div class="field">
              <label>类型</label>
              <select v-model="form.order_type" class="inp">
                <option value="market">市价</option>
                <option value="limit">限价</option>
              </select>
            </div>
            <div class="field" v-if="form.order_type === 'limit'">
              <label>价格</label>
              <input v-model.number="form.price" type="number" class="inp num-inp" step="0.01" />
            </div>
            <div class="field">
              <label>数量</label>
              <input v-model.number="form.qty" type="number" class="inp num-inp" step="100" min="100" />
            </div>
            <div class="field submit-field">
              <button class="submit-btn" :class="form.side" @click="submitOrder" :disabled="submitting">
                <Icon v-if="submitting" name="refresh" :size="14" class="spin" />
                {{ submitting ? '提交中…' : (form.side === 'buy' ? '买入' : '卖出') }}
              </button>
            </div>
          </div>
        </div>
      </Card>

      <!-- pending orders -->
      <Card class="mt" v-if="orders.length">
        <template #header>
          <span class="card-title">订单 ({{ orders.length }})</span>
        </template>
        <table class="tbl">
          <thead>
            <tr>
              <th>时间</th><th>方向</th><th>代码</th><th>名称</th><th class="ar">价格</th><th class="ar">数量</th><th>状态</th><th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="o in orders" :key="o.id">
              <td class="muted">{{ o.created_at?.slice(5, 16) }}</td>
              <td><span :class="['side-tag', o.side]">{{ o.side === 'buy' ? '买' : '卖' }}</span></td>
              <td class="code">{{ o.code }}</td>
              <td>{{ o.name }}</td>
              <td class="ar num">{{ o.filled_price?.toFixed(2) ?? o.price.toFixed(2) }}</td>
              <td class="ar num">{{ o.qty.toLocaleString() }}</td>
              <td>
                <span :class="['status-tag', o.status]">
                  {{ o.status === 'filled' ? '已成交' : o.status === 'pending' ? '挂单中' : o.status === 'cancelled' ? '已撤单' : o.status }}
                </span>
              </td>
              <td>
                <button v-if="o.status === 'pending'" class="btn-sm danger" @click="handleCancel(o.id)" title="撤单">
                  <Icon name="close" :size="13" />
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </Card>
    </template>
  </div>
</template>

<style scoped>
.stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: var(--sp-3); margin-bottom: var(--sp-4); }
.mt { margin-top: var(--sp-4); }
.card-title { font-weight: 600; font-size: var(--fs-md); }
.sel, .inp {
  background: var(--bg); border: 1px solid var(--border); border-radius: var(--radius-sm);
  padding: 7px 10px; color: var(--text); font-size: var(--fs-sm);
}
.sel:focus, .inp:focus { border-color: var(--gold); outline: none; }
.btn-sm {
  display: inline-flex; align-items: center; justify-content: center;
  width: 32px; height: 32px; border-radius: var(--radius-sm);
  background: var(--bg-raised); border: 1px solid var(--border); color: var(--text-sub);
  cursor: pointer; transition: color var(--dur-fast);
}
.btn-sm:hover { color: var(--gold); border-color: var(--gold); }
.btn-sm.danger:hover { color: var(--up); border-color: var(--up); }
.btn-sm.retry { width: auto; padding: 8px 16px; font-size: var(--fs-sm); }

.form { padding: var(--sp-2) 0; }
.form-row { display: flex; align-items: flex-end; gap: var(--sp-3); flex-wrap: wrap; }
.field { display: flex; flex-direction: column; gap: 4px; }
.field label { font-size: var(--fs-xs); color: var(--text-faint); }
.code-inp { width: 90px; font-family: var(--font-mono); }
.num-inp { width: 100px; }
.submit-field { align-self: flex-end; }
.side-toggle { display: flex; gap: 2px; }
.side-btn {
  padding: 7px 16px; border: 1px solid var(--border); background: transparent;
  color: var(--text-sub); font-size: var(--fs-sm); cursor: pointer; font-weight: 600;
  transition: all var(--dur-fast);
}
.side-btn.buy { border-radius: var(--radius-sm) 0 0 var(--radius-sm); }
.side-btn.sell { border-radius: 0 var(--radius-sm) var(--radius-sm) 0; }
.side-btn.buy.active { background: var(--up); color: #fff; border-color: var(--up); }
.side-btn.sell.active { background: var(--down); color: #fff; border-color: var(--down); }
.submit-btn {
  padding: 8px 20px; border: none; border-radius: var(--radius-sm);
  font-weight: 700; font-size: var(--fs-md); cursor: pointer; color: #fff;
  display: inline-flex; align-items: center; gap: var(--sp-2);
  transition: opacity var(--dur-fast);
}
.submit-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.submit-btn.buy { background: var(--up); }
.submit-btn.sell { background: var(--down); }

.tbl { width: 100%; border-collapse: collapse; font-size: var(--fs-sm); }
.tbl th { padding: 10px var(--sp-3); text-align: left; color: var(--text-sub); border-bottom: 1px solid var(--border); }
.tbl .ar { text-align: right; }
.tbl tr:hover { background: var(--bg-hover); }
.tbl td { padding: 10px var(--sp-3); border-bottom: 1px solid var(--border-soft); color: var(--text); }
.code { font-family: var(--font-mono); }
.muted { color: var(--text-faint); font-size: var(--fs-xs); }
.side-tag { font-size: var(--fs-xs); font-weight: 600; padding: 2px 6px; border-radius: 3px; }
.side-tag.buy { background: rgba(232, 64, 64, 0.15); color: var(--up); }
.side-tag.sell { background: rgba(45, 183, 87, 0.15); color: var(--down); }
.status-tag { font-size: var(--fs-xs); padding: 2px 6px; border-radius: 3px; }
.status-tag.filled { background: rgba(45, 183, 87, 0.15); color: var(--down); }
.status-tag.pending { background: rgba(232, 184, 75, 0.15); color: var(--gold); }
.status-tag.cancelled { background: rgba(138, 143, 154, 0.15); color: var(--text-faint); }
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
