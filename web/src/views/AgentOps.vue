<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import PageHeader from '@/components/PageHeader.vue'
import Card from '@/components/Card.vue'
import StatCard from '@/components/StatCard.vue'
import EmptyState from '@/components/EmptyState.vue'
import Skeleton from '@/components/Skeleton.vue'
import Icon from '@/components/Icon.vue'
import { useToastStore } from '@/stores/toast'
import { getAgentStrategies, scanEntry, deepAnalyze, portfolioRebalance, listAccounts } from '@/api'
import type { StrategyDef, ScanResult, DeepEntry, PortfolioSnapshot, AccountSummary } from '@/api'

const toast = useToastStore()
const router = useRouter()
const strategies = ref<StrategyDef[]>([])
const accounts = ref<AccountSummary[]>([])
const loading = ref(true)
const scanResult = ref<ScanResult | null>(null)
const deepResults = ref<DeepEntry[]>([])
const portfolio = ref<PortfolioSnapshot | null>(null)

const scanCode = ref('')
const scanStrategy = ref<Record<string, unknown> | null>(null)
const selectedStratId = ref('')
const scanning = ref(false)
const deepCodes = ref('')
const deepRunning = ref(false)
const portfolioId = ref<number | null>(null)

onMounted(async () => {
  try {
    const [s, a] = await Promise.all([getAgentStrategies(), listAccounts()])
    strategies.value = s
    accounts.value = a
    if (s.length) { scanStrategy.value = s[0] as unknown as Record<string, unknown>; selectedStratId.value = s[0].id }
    if (a.length) portfolioId.value = a[0].account_id
  } finally { loading.value = false }
})

async function doScan() {
  if (!scanCode.value || !scanStrategy.value) { toast.error('请输入代码并选择策略'); return }
  scanning.value = true; scanResult.value = null
  try {
    scanResult.value = await scanEntry(scanCode.value, scanStrategy.value)
    toast.success(scanResult.value.triggered ? '信号触发！' : '信号未触发')
  } catch (e: unknown) { toast.error('扫描失败：' + (e instanceof Error ? e.message : String(e))) }
  finally { scanning.value = false }
}

async function doDeep() {
  const codes = deepCodes.value.split(/[,，\s]+/).filter(Boolean)
  if (!codes.length) { toast.error('请输入股票代码'); return }
  deepRunning.value = true; deepResults.value = []
  try {
    const r = await deepAnalyze(codes)
    deepResults.value = r.entries || []
    toast.success(`分析完成，${deepResults.value.length} 只`)
  } catch (e: unknown) { toast.error('深挖失败：' + (e instanceof Error ? e.message : String(e))) }
  finally { deepRunning.value = false }
}

async function doPortfolio() {
  if (!portfolioId.value) { toast.error('请选择账户'); return }
  try { portfolio.value = await portfolioRebalance(portfolioId.value) }
  catch (e: unknown) { toast.error('获取失败：' + (e instanceof Error ? e.message : String(e))) }
}

function handToAI(s: StrategyDef) {
  router.push({ path: '/agent', query: { prompt: `用 ${s.name} 策略分析当前机会并给出操作建议` } })
}

function fmtMoney(v: number) {
  if (Math.abs(v) >= 1e4) return (v / 1e4).toFixed(2) + '万'
  return v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}
function verdictColor(v: string) {
  if (v === '前置') return 'up'
  if (v === '剔名' || v === '剔除') return 'down'
  if (v === '保持') return 'flat'
  if (v === '后移') return 'gold'
  return 'flat'
}
</script>

<template>
  <div class="agentops">
    <PageHeader title="AI 操盘" subtitle="信号扫描 · 个股深挖 · 组合重平衡" />

    <Skeleton v-if="loading" />

    <!-- strategies -->
    <section class="sec" v-if="strategies.length">
      <h2 class="sec-title"><Icon name="layers" :size="18" /> 可用策略</h2>
      <div class="strat-row">
        <Card v-for="s in strategies" :key="s.id" padding :highlight="selectedStratId === s.id"
          @click="scanStrategy = s as unknown as Record<string, unknown>; selectedStratId = s.id" class="strat-card">
          <div class="strat-name">{{ s.name }}</div>
          <div class="strat-desc muted">{{ s.desc }}</div>
          <button class="ai-link" @click.stop="handToAI(s)">交给 AI 操盘</button>
        </Card>
      </div>
    </section>

    <!-- scan -->
    <section class="sec">
      <h2 class="sec-title"><Icon name="search" :size="18" /> 信号扫描</h2>
      <Card padding>
        <div class="scan-form">
          <input v-model="scanCode" class="inp code-inp" placeholder="股票代码 如 600519" @keyup.enter="doScan" />
          <button class="btn gold-btn" @click="doScan" :disabled="scanning">
            <Icon v-if="scanning" name="refresh" :size="14" class="spin" />
            {{ scanning ? '扫描中…' : '扫描' }}
          </button>
        </div>
        <div v-if="scanResult" class="scan-result">
          <div class="scan-code num">{{ scanResult.code }}</div>
          <div :class="['scan-signal', scanResult.triggered ? 'up' : 'down']">
            <Icon :name="scanResult.triggered ? 'check' : 'close'" :size="16" />
            {{ scanResult.triggered ? '信号触发' : '信号未触发' }}
          </div>
          <div class="scan-price muted">现价: {{ scanResult.price.toFixed(2) }}</div>
        </div>
      </Card>
    </section>

    <!-- deep analysis -->
    <section class="sec">
      <h2 class="sec-title"><Icon name="research" :size="18" /> 个股深挖</h2>
      <Card padding>
        <div class="scan-form">
          <input v-model="deepCodes" class="inp" style="flex:1" placeholder="输入代码，逗号分隔 如 600519,000858" @keyup.enter="doDeep" />
          <button class="btn" @click="doDeep" :disabled="deepRunning">
            <Icon v-if="deepRunning" name="refresh" :size="14" class="spin" />
            {{ deepRunning ? '分析中…' : '深挖' }}
          </button>
        </div>
        <div v-if="deepResults.length" class="deep-list">
          <div v-for="d in deepResults" :key="d.code" class="deep-item">
            <div class="deep-hd">
              <span class="code num">{{ d.code }}</span>
              <span class="deep-name">{{ d.name }}</span>
              <span :class="['verdict', verdictColor(d.verdict)]">{{ d.verdict }}</span>
            </div>
            <div class="deep-reason">{{ d.reason }}</div>
            <div class="deep-conf muted">置信度: {{ (d.confidence * 100).toFixed(0) }}%</div>
          </div>
        </div>
      </Card>
    </section>

    <!-- portfolio -->
    <section class="sec">
      <h2 class="sec-title"><Icon name="holdings" :size="18" /> 组合重平衡</h2>
      <Card padding>
        <div class="scan-form">
          <select v-if="accounts.length" v-model="portfolioId" class="inp">
            <option v-for="a in accounts" :key="a.account_id" :value="a.account_id">{{ a.name }}</option>
          </select>
          <button class="btn" @click="doPortfolio">获取持仓</button>
        </div>
        <template v-if="portfolio">
          <div class="pf-grid">
            <StatCard label="总资产" :value="fmtMoney(portfolio.total_assets)" icon="wallet" />
            <StatCard label="可用现金" :value="fmtMoney(portfolio.cash)" />
            <StatCard label="持仓数" :value="String(Object.keys(portfolio.holdings).length)" unit="只" />
          </div>
          <div class="weights" v-if="Object.keys(portfolio.current_weights).length">
            <div v-for="(w, code) in portfolio.current_weights" :key="code" class="weight-row">
              <span class="code num">{{ code }}</span>
              <div class="bar-bg">
                <div class="bar-fill" :style="{ width: (w as number * 100).toFixed(1) + '%' }" />
              </div>
              <span class="weight-val num">{{ ((w as number) * 100).toFixed(1) }}%</span>
            </div>
          </div>
          <EmptyState v-else message="空仓" />
        </template>
      </Card>
    </section>
  </div>
</template>

<style scoped>
.agentops { max-width: 900px; }
.sec { margin-bottom: var(--sp-6); }
.sec-title {
  font-size: var(--fs-lg); font-weight: 600; color: var(--text); margin: 0 0 var(--sp-4);
  display: flex; align-items: center; gap: var(--sp-2);
}
.strat-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: var(--sp-3); }
.strat-card { cursor: pointer; }
.strat-name { font-weight: 700; color: var(--gold); margin-bottom: 2px; }
.strat-desc { font-size: var(--fs-sm); }
.ai-link {
  margin-top: var(--sp-2); padding: 0; border: none; background: transparent;
  color: var(--accent); font-size: var(--fs-xs); cursor: pointer; font-weight: 600;
}
.ai-link:hover { color: var(--accent-hover); text-decoration: underline; }
.scan-form { display: flex; gap: var(--sp-2); align-items: center; margin-bottom: var(--sp-3); }
.code-inp { width: 140px; font-family: var(--font-mono); }
.inp {
  background: var(--bg); border: 1px solid var(--border); border-radius: var(--radius-sm);
  padding: 7px 10px; color: var(--text); font-size: var(--fs-sm);
}
.inp:focus { border-color: var(--gold); outline: none; }
.btn {
  display: inline-flex; align-items: center; gap: var(--sp-2);
  padding: 7px 14px; border: 1px solid var(--border); border-radius: var(--radius-sm);
  background: var(--bg-raised); color: var(--text-sub); font-size: var(--fs-sm); cursor: pointer;
  transition: all var(--dur-fast);
}
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.gold-btn { background: var(--gold); color: var(--on-gold); border-color: var(--gold); font-weight: 600; }
.gold-btn:hover { background: var(--gold-hover); }
.scan-result { display: flex; align-items: center; gap: var(--sp-4); padding: var(--sp-3) 0; }
.scan-code { font-size: var(--fs-lg); font-weight: 700; }
.scan-signal { display: flex; align-items: center; gap: var(--sp-1); font-weight: 600; font-size: var(--fs-md); }
.scan-price { margin-left: auto; }
.deep-list { display: flex; flex-direction: column; gap: var(--sp-3); }
.deep-item { padding: var(--sp-3) 0; border-bottom: 1px solid var(--border-soft); }
.deep-hd { display: flex; align-items: center; gap: var(--sp-3); margin-bottom: 4px; }
.code { font-family: var(--font-mono); }
.deep-name { font-weight: 600; }
.verdict { font-size: var(--fs-sm); font-weight: 600; padding: 2px 8px; border-radius: var(--radius-pill); }
.verdict.up { background: rgba(229, 72, 77, 0.15); color: var(--up); }
.verdict.down { background: rgba(63, 185, 80, 0.15); color: var(--down); }
.verdict.flat { background: rgba(154, 163, 176, 0.15); color: var(--text-sub); }
.verdict.gold { background: var(--gold-dim); color: var(--gold); }
.deep-reason { font-size: var(--fs-sm); color: var(--text-sub); margin-bottom: 2px; }
.deep-conf { font-size: var(--fs-xs); }
.pf-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: var(--sp-3); margin: var(--sp-3) 0; }
.weights { display: flex; flex-direction: column; gap: var(--sp-2); margin-top: var(--sp-3); }
.weight-row { display: flex; align-items: center; gap: var(--sp-3); }
.bar-bg { flex: 1; height: 6px; background: var(--bg); border-radius: 3px; overflow: hidden; }
.bar-fill { height: 100%; background: var(--gold); border-radius: 3px; transition: width var(--dur) var(--ease); }
.weight-val { font-size: var(--fs-sm); min-width: 50px; text-align: right; }
.muted { color: var(--text-faint); font-size: var(--fs-sm); }
.gold { color: var(--gold); }
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
