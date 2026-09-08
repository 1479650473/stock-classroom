<script setup lang="ts">
import { ref, computed } from 'vue'

// 嵌入模式: 隐藏页面标题(供数据页 Tab 内嵌)
withDefaults(defineProps<{ embedded?: boolean }>(), { embedded: false })
import PageHeader from '@/components/PageHeader.vue'
import Card from '@/components/Card.vue'
import StatCard from '@/components/StatCard.vue'
import EmptyState from '@/components/EmptyState.vue'
import KlineChart from '@/components/KlineChart.vue'
import Icon from '@/components/Icon.vue'
import { useToastStore } from '@/stores/toast'
import { startTrainer, trainerStep, trainerStepBack, trainerGoto, trainerOrder, trainerBars, endTrainer } from '@/api'
import type { TrainerSnapshot, KlineBar } from '@/api'

const toast = useToastStore()
const code = ref('')
const sid = ref<number | null>(null)
const snap = ref<TrainerSnapshot | null>(null)
const bars = ref<KlineBar[]>([])
const loading = ref(false)
const qty = ref(100)

const visibleBars = computed(() => {
  if (!snap.value || !bars.value.length) return []
  return bars.value.slice(0, snap.value.cursor + 1)
})

async function start() {
  if (!code.value) { toast.error('请输入代码'); return }
  loading.value = true
  try {
    const r = await startTrainer(code.value, 250)
    sid.value = r.session_id
    snap.value = r.snapshot
    bars.value = await trainerBars(r.session_id)
    toast.success(`训练会话已创建，共 ${r.total_bars} 根K线`)
  } catch (e: unknown) {
    toast.error('启动失败：' + (e instanceof Error ? e.message : String(e)))
  } finally { loading.value = false }
}

async function step() {
  if (!sid.value) return
  try {
    const r = await trainerStep(sid.value)
    snap.value = r.snapshot
  } catch (e: unknown) { toast.error('前进失败：' + (e instanceof Error ? e.message : String(e))) }
}
async function stepBack() {
  if (!sid.value) return
  try {
    const r = await trainerStepBack(sid.value)
    snap.value = r.snapshot
  } catch (e: unknown) { toast.error('后退失败：' + (e instanceof Error ? e.message : String(e))) }
}
async function gotoIdx(idx: number) {
  if (!sid.value) return
  try {
    const r = await trainerGoto(sid.value, idx)
    snap.value = r.snapshot
  } catch (e: unknown) { toast.error('跳转失败：' + (e instanceof Error ? e.message : String(e))) }
}
async function buy() {
  if (!sid.value) return
  try {
    const r = await trainerOrder(sid.value, 'long', qty.value)
    snap.value = r.snapshot
    toast.success('买入成功')
  } catch (e: unknown) { toast.error('买入失败：' + (e instanceof Error ? e.message : String(e))) }
}
async function sell() {
  if (!sid.value) return
  try {
    const r = await trainerOrder(sid.value, 'short', qty.value)
    snap.value = r.snapshot
    toast.success('卖出成功')
  } catch (e: unknown) { toast.error('卖出失败：' + (e instanceof Error ? e.message : String(e))) }
}

async function end() {
  if (!sid.value) return
  try {
    await endTrainer(sid.value)
    sid.value = null
    snap.value = null
    bars.value = []
    toast.success('训练会话已结束')
  } catch (e: unknown) { toast.error('结束失败：' + (e instanceof Error ? e.message : String(e))) }
}

function fmtMoney(v: number) {
  return v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}
</script>

<template>
  <div>
    <PageHeader title="训练" subtitle="K线回放交易模拟器" :embedded="embedded">
      <template #right>
        <div class="start-row" v-if="!sid">
          <input v-model="code" class="inp code-inp" placeholder="股票代码" @keyup.enter="start" />
          <button class="btn gold-btn" @click="start" :disabled="loading">
            <Icon :name="loading ? 'refresh' : 'play'" :size="14" :class="{ spin: loading }" />
            {{ loading ? '加载中…' : '开始训练' }}
          </button>
        </div>
      </template>
    </PageHeader>

    <EmptyState v-if="!sid" message="输入股票代码，开始K线回放训练">
      <template #action><span class="muted">逐根K线下单，训练交易直觉</span></template>
    </EmptyState>

    <template v-if="sid && snap">
      <!-- chart -->
      <KlineChart :bars="visibleBars" />

      <!-- controls -->
      <Card class="mt">
        <div class="ctrl-row">
          <div class="nav-btns">
            <button class="ctrl-btn" @click="gotoIdx(0)" title="回到起点"><Icon name="chevron-left" :size="16" /><Icon name="chevron-left" :size="16" /></button>
            <button class="ctrl-btn" @click="stepBack" :disabled="snap.cursor <= 0" title="后退一步"><Icon name="chevron-left" :size="16" /></button>
            <span class="cursor-info num">{{ snap.current_date }} ({{ snap.cursor + 1 }}/{{ snap.total_bars }})</span>
            <button class="ctrl-btn" @click="step" :disabled="snap.cursor >= snap.total_bars - 1" title="前进一步"><Icon name="chevron-right" :size="16" /></button>
          </div>
          <div class="trade-btns">
            <button class="ctrl-btn danger" @click="end" title="结束会话">
              <Icon name="stop" :size="14" />
            </button>
            <div class="qty-row">
              <label class="muted">数量</label>
              <input v-model.number="qty" type="number" class="inp num-inp" step="100" min="100" />
            </div>
            <button class="ctrl-btn buy-btn" @click="buy" title="买入">买</button>
            <button class="ctrl-btn sell-btn" @click="sell" title="卖出">卖</button>
          </div>
        </div>
        <div class="bar-track">
          <div class="bar-fill" :style="{ width: (snap.progress * 100) + '%' }" />
        </div>
      </Card>

      <!-- stats -->
      <div class="stats">
        <StatCard label="总资产" :value="fmtMoney(snap.total_equity)" icon="wallet" />
        <StatCard label="余额" :value="fmtMoney(snap.balance)" />
        <StatCard label="浮动盈亏" :value="fmtMoney(snap.floating_pnl)" :trend="snap.floating_pnl >= 0 ? 'up' : 'down'" />
        <StatCard label="已实现盈亏" :value="fmtMoney(snap.realized_pnl)" :trend="snap.realized_pnl >= 0 ? 'up' : 'down'" />
        <StatCard label="胜率" :value="(snap.win_rate * 100).toFixed(0) + '%'" />
        <StatCard label="当前价" :value="snap.current_price.toFixed(2)" />
      </div>
    </template>
  </div>
</template>

<style scoped>
.start-row { display: flex; gap: var(--sp-2); align-items: center; }
.code-inp { width: 110px; font-family: var(--font-mono); }
.inp {
  background: var(--bg); border: 1px solid var(--border); border-radius: var(--radius-sm);
  padding: 6px 10px; color: var(--text); font-size: var(--fs-sm);
}
.inp:focus { border-color: var(--gold); outline: none; }
.num-inp { width: 80px; }
.mt { margin-top: var(--sp-4); }
.ctrl-row { display: flex; justify-content: space-between; align-items: center; margin-bottom: var(--sp-3); }
.nav-btns { display: flex; align-items: center; gap: var(--sp-2); }
.trade-btns { display: flex; align-items: center; gap: var(--sp-2); }
.qty-row { display: flex; align-items: center; gap: var(--sp-1); }
.ctrl-btn {
  display: inline-flex; align-items: center; justify-content: center;
  min-width: 32px; height: 32px; padding: 0 8px; border: 1px solid var(--border);
  border-radius: var(--radius-sm); background: var(--bg-raised); color: var(--text-sub);
  cursor: pointer; font-size: var(--fs-sm); font-weight: 600;
  transition: all var(--dur-fast);
}
.ctrl-btn:hover { border-color: var(--accent); color: var(--text); }
.ctrl-btn.danger:hover { border-color: var(--up); color: var(--up); }
.ctrl-btn:disabled { opacity: 0.3; cursor: not-allowed; }
.buy-btn { background: var(--up); color: #fff; border-color: var(--up); }
.sell-btn { background: var(--down); color: #fff; border-color: var(--down); }
.cursor-info { font-size: var(--fs-sm); color: var(--text-sub); min-width: 140px; text-align: center; }
.bar-track { height: 4px; background: var(--bg); border-radius: 2px; overflow: hidden; }
.bar-fill { height: 100%; background: var(--gold); border-radius: 2px; transition: width 0.15s; }
.stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: var(--sp-3); margin-top: var(--sp-4); }
.gold-btn { background: var(--gold); color: var(--on-gold); border-color: var(--gold); font-weight: 600; }
.gold-btn:hover { background: var(--gold-hover); }
.btn {
  display: inline-flex; align-items: center; gap: var(--sp-2);
  padding: 7px 14px; border: 1px solid var(--border); border-radius: var(--radius-sm);
  background: var(--bg-raised); color: var(--text-sub); font-size: var(--fs-sm); cursor: pointer;
}
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.muted { color: var(--text-faint); font-size: var(--fs-sm); }
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
