<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref } from 'vue'
import PageHeader from '@/components/PageHeader.vue'
import Card from '@/components/Card.vue'
import Skeleton from '@/components/Skeleton.vue'
import EmptyState from '@/components/EmptyState.vue'
import Icon from '@/components/Icon.vue'
import { useToastStore } from '@/stores/toast'
import { getPicks, runPicks, listAccounts, placeOrder } from '@/api'
import type { PickItem, AccountSummary } from '@/api'

const toast = useToastStore()
const items = ref<PickItem[]>([])
const loading = ref(true)
const stale = ref(true)
const running = ref(false)
const accounts = ref<AccountSummary[]>([])
const buyAccount = ref<number | null>(null)
const buyQty = ref(100)
const buying = ref<Record<string, boolean>>({})
let pollTimer: ReturnType<typeof setInterval> | null = null

onMounted(async () => {
  await Promise.all([loadAccounts(), load()])
})

onBeforeUnmount(() => {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
})

async function loadAccounts() {
  try {
    accounts.value = await listAccounts()
    if (accounts.value.length) buyAccount.value = accounts.value[0].account_id
  } catch { /* ignore */ }
}

async function load() {
  loading.value = true
  try {
    const d = await getPicks(20)
    items.value = d.items
    stale.value = d.stale
  } catch (e) {
    toast.error('选股加载失败：' + (e instanceof Error ? e.message : String(e)))
  } finally { loading.value = false }
}

async function rescan() {
  running.value = true
  toast.info('开始扫描候选池…')
  try {
    await runPicks(true)
    toast.success('扫描排队中，稍后自动刷新')
    // 轮询直到非 stale
    let tries = 0
    pollTimer = setInterval(async () => {
      tries++
      try {
        const d = await getPicks(20)
        if (!d.stale || tries > 30) {
          clearIfPoll()
          items.value = d.items
          stale.value = d.stale
          toast.success('选股已更新')
          running.value = false
        }
      } catch { /* 轮询瞬断忽略 */ }
    }, 3000)
  } catch (e) {
    toast.error('扫描失败：' + (e instanceof Error ? e.message : String(e)))
    running.value = false
  }
}

function clearIfPoll() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
}

async function buy(p: PickItem) {
  if (!buyAccount.value) { toast.error('请先选择账户'); return }
  if (!buyQty.value || buyQty.value <= 0) { toast.error('请输入数量'); return }
  buying.value = { ...buying.value, [p.code]: true }
  try {
    const r = await placeOrder({
      account_id: buyAccount.value,
      code: p.code,
      name: p.name,
      side: 'buy',
      order_type: 'limit',   // 用选股价挂限价单, 不用拉实时价(避免被反爬)
      price: p.price,
      qty: buyQty.value,
    })
    toast.success(`已提交买入 ${p.name} (${p.code})`)
  } catch (e) {
    toast.error('买入失败：' + (e instanceof Error ? e.message : String(e)))
  } finally { buying.value = { ...buying.value, [p.code]: false } }
}

function fmtPct(v: number) { return (v >= 0 ? '+' : '') + v.toFixed(2) + '%' }
function fmtScore(v: number) { return v.toFixed(1) }
function grouptip(g: Record<string, unknown>[] | undefined): string {
  if (!Array.isArray(g) || !g.length) return ''
  // g 是分组数组 [{id, name, indicators, max_score, min_score,...}]
  return g.map((grp) => {
    const n = (grp.name as string) || (grp.id as string) || ''
    const max = typeof grp.max_score === 'number' ? grp.max_score : (grp as Record<string, unknown>).score
    return typeof max === 'number' ? `${n}:${max.toFixed(1)}` : n
  }).join(' · ')
}
</script>

<template>
  <div>
    <PageHeader title="选股" subtitle="多因子评分 Top 20 · 一键模拟买入">
      <template #right>
        <select v-if="accounts.length" v-model="buyAccount" class="sel" title="买入账户">
          <option v-for="a in accounts" :key="a.account_id" :value="a.account_id">{{ a.name }}</option>
        </select>
        <span v-if="stale" class="tag warn">缓存 · 可刷新</span>
        <button class="btn" :disabled="running" @click="rescan">
          <Icon v-if="running" name="refresh" :size="14" class="spin" />
          {{ running ? '扫描中…' : '重新扫描' }}
        </button>
      </template>
    </PageHeader>

    <Skeleton v-if="loading && !items.length" />

    <EmptyState v-if="!loading && !items.length && !stale" message="暂无选股结果，点击「重新扫描」" />

    <Card v-if="items.length">
      <div class="buy-bar">
        <label class="qty-lbl">买入数量</label>
        <input v-model.number="buyQty" type="number" class="inp qty-inp" step="100" min="100" />
        <span class="muted hint">按当前选中账户 · 限价挂单</span>
      </div>
      <table class="tbl">
        <thead>
          <tr>
            <th>#</th><th>代码</th><th>名称</th><th class="ar">现价</th><th class="ar">涨跌</th>
            <th class="ar">评分</th><th>因子</th><th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(p, i) in items" :key="p.code">
            <td class="muted">{{ i + 1 }}</td>
            <td class="code num">{{ p.code }}</td>
            <td>{{ p.name }}</td>
            <td class="ar num">{{ p.price.toFixed(2) }}</td>
            <td class="ar num" :class="p.change_pct >= 0 ? 'up' : 'down'">{{ fmtPct(p.change_pct) }}</td>
            <td class="ar num gold">{{ fmtScore(p.score) }}</td>
            <td class="muted gtip" :title="grouptip(p.groups)">{{ grouptip(p.groups).slice(0, 18) }}…</td>
            <td class="ar">
              <button class="buy-btn" :disabled="buying[p.code]" @click="buy(p)">
                {{ buying[p.code] ? '…' : '买入' }}
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </Card>
  </div>
</template>

<style scoped>
.sel {
  background: var(--bg); border: 1px solid var(--border); border-radius: var(--radius-sm);
  padding: 6px 10px; color: var(--text); font-size: var(--fs-sm);
}
.sel:focus { border-color: var(--gold); outline: none; }
.tag { font-size: var(--fs-xs); padding: 2px 8px; border-radius: var(--radius-pill); }
.tag.warn { color: var(--gold); border: 1px solid var(--gold); }
.btn {
  display: inline-flex; align-items: center; gap: 4px; padding: 7px 14px; border: none;
  border-radius: var(--radius-sm); background: var(--gold); color: #fff; font-weight: 700;
  font-size: var(--fs-sm); cursor: pointer;
}
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.buy-bar { display: flex; align-items: center; gap: var(--sp-2); padding: var(--sp-3) 0 var(--sp-2); }
.qty-lbl { font-size: var(--fs-sm); color: var(--text-sub); }
.qty-inp { width: 90px; background: var(--bg); border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 6px 10px; color: var(--text); }
.qty-inp:focus { border-color: var(--gold); outline: none; }
.hint { font-size: var(--fs-xs); }
.tbl { width: 100%; border-collapse: collapse; font-size: var(--fs-sm); }
.tbl th { padding: 10px var(--sp-3); text-align: left; color: var(--text-sub); border-bottom: 1px solid var(--border); }
.tbl .ar { text-align: right; }
.tbl tr:hover { background: var(--bg-hover); }
.tbl td { padding: 10px var(--sp-3); border-bottom: 1px solid var(--border-soft); color: var(--text); }
.code { font-family: var(--font-mono); }
.up { color: var(--up); } .down { color: var(--down); }
.gold { color: var(--gold); font-weight: 700; }
.muted { color: var(--text-faint); }
.gtip { font-size: var(--fs-xs); max-width: 180px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.buy-btn {
  padding: 4px 12px; border: 1px solid var(--up); background: rgba(232, 64, 64, 0.1);
  color: var(--up); border-radius: var(--radius-sm); font-size: var(--fs-xs); font-weight: 700; cursor: pointer;
  transition: all var(--dur-fast);
}
.buy-btn:hover { background: var(--up); color: #fff; }
.buy-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
