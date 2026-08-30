<script setup lang="ts">
import { onMounted, ref, shallowRef, computed } from 'vue'
import PageHeader from '@/components/PageHeader.vue'
import Card from '@/components/Card.vue'
import StatCard from '@/components/StatCard.vue'
import Skeleton from '@/components/Skeleton.vue'
import EmptyState from '@/components/EmptyState.vue'
import Icon from '@/components/Icon.vue'
import { useToastStore } from '@/stores/toast'
import { api, type JobHandle } from '@/api/client'
import {
  getRegime, getFactors, getStrategies,
  runBacktest, runStudy, runPaper, runCompare,
  type RegimeData, type FactorDef, type StrategyDef, type BacktestResult,
} from '@/api'
import * as echarts from 'echarts'

const toast = useToastStore()
const regime = ref<RegimeData | null>(null)
const factors = ref<FactorDef[]>([])
const strategies = ref<StrategyDef[]>([])
const loading = ref(true)
const regimeLoading = ref(true)

// 页签: 因子研究 / 策略回测 / 组合纸面盘
type Tab = 'study' | 'backtest' | 'compare'
const tab = ref<Tab>('backtest')
const tabs: { id: Tab; label: string; icon: string }[] = [
  { id: 'backtest', label: '策略回测', icon: 'backtest' },
  { id: 'study', label: '因子研究', icon: 'research' },
  { id: 'compare', label: '策略对比', icon: 'compare' },
]

onMounted(async () => {
  try {
    const [f, s] = await Promise.all([getFactors(), getStrategies()])
    factors.value = f
    strategies.value = s
  } finally { loading.value = false }
  try { regime.value = await getRegime() } finally { regimeLoading.value = false }
})

const regimeColor = (r: string) => r === 'bull' ? 'up' : r === 'bear' ? 'down' : 'flat'
const regimeLabel: Record<string, string> = { bull: '牛市', bear: '熊市', range: '震荡' }

// ──── 策略回测 ────
const btContractName = ref('F价值Tilt')
const btStart = ref('2024-01-01')
const btEnd = ref('2026-08-27')
const btRunning = ref(false)
const btResult = shallowRef<BacktestResult | null>(null)
const btChartEl = ref<HTMLElement | null>(null)
const btChart = shallowRef<echarts.ECharts | null>(null)

function drawBtChart() {
  if (!btResult.value || !btChartEl.value) return
  if (!btChart.value) btChart.value = echarts.init(btChartEl.value)
  const nav = btResult.value.nav || []
  const dates = btResult.value.dates || []
  btChart.value.setOption({
    grid: { left: 50, right: 16, top: 20, bottom: 28 },
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: dates, axisLabel: { show: false } },
    yAxis: { type: 'value', scale: true },
    series: [{
      type: 'line', data: nav, smooth: true, showSymbol: false,
      lineStyle: { color: '#D4A574', width: 2 },
      areaStyle: { color: 'rgba(212,165,116,0.12)' },
    }],
  })
}

// 轮询 job 状态(替代 SSE, 避开 vite proxy 对 event-stream 的缓冲问题)
function pollJob<T>(job: JobHandle, onDone: (res: T) => void, onErr: (m: string) => void) {
  const id = job.job_id
  let tries = 0
  const timer = setInterval(async () => {
    tries++
    try {
      const rec = await api.get<{ status: string; result: T | null; error: string | null }>(`/api/jobs/${id}`)
      if (rec.status === 'succeeded' && rec.result) {
        clearInterval(timer); onDone(rec.result)
      } else if (rec.status === 'failed') {
        clearInterval(timer); onErr(rec.error || '任务失败')
      } else if (tries > 200) {
        clearInterval(timer); onErr('任务超时')
      }
    } catch { /* 忽略瞬时错误 */ }
  }, 1500)
}

async function doBacktest() {
  if (!btContractName.value) { toast.error('请选择策略'); return }
  btRunning.value = true
  btResult.value = null
  toast.info('回测排队中…')
  try {
    const job = await runBacktest({ id: btContractName.value }, btStart.value, btEnd.value)
    pollJob<BacktestResult>(job, (res) => {
      btResult.value = res
      setTimeout(() => drawBtChart(), 50)
      toast.success('回测完成')
    }, (m) => toast.error(m))
  } catch (e) {
    toast.error('回测失败：' + (e instanceof Error ? e.message : String(e)))
  } finally { btRunning.value = false }
}

// ──── 因子研究 ────
const studyFactor = ref('BP')
const studyRunning = ref(false)
const studyResult = shallowRef<Record<string, unknown> | null>(null)
async function doStudy() {
  studyRunning.value = true; studyResult.value = null; toast.info('因子研究排队…')
  try {
    const job = await runStudy(studyFactor.value, { holding_period: 20, start: '2023-01-01' })
    pollJob<Record<string, unknown>>(job, (res) => { studyResult.value = res; toast.success('研究完成') }, (m) => toast.error(m))
  } catch (e) { toast.error('研究失败：' + (e instanceof Error ? e.message : String(e))) }
  finally { studyRunning.value = false }
}

// ──── 策略对比 ────
const cmpRunning = ref(false)
const cmpResult = shallowRef<Record<string, { metrics: Record<string, number>; nav: number[]; dates: string[] }> | null>(null)
async function doCompare() {
  cmpRunning.value = true; cmpResult.value = null; toast.info('策略对比排队…')
  try {
    const job = await runCompare('2024-01-01', '2026-08-27')
    pollJob<{ strategies: typeof cmpResult.value }>(job, (res) => { cmpResult.value = res.strategies; toast.success('对比完成') }, (m) => toast.error(m))
  } catch (e) { toast.error('对比失败：' + (e instanceof Error ? e.message : String(e))) }
  finally { cmpRunning.value = false }
}

const cmpRows = computed(() => {
  if (!cmpResult.value) return []
  const arr = Object.entries(cmpResult.value).map(([name, s]) => {
    const m = s.metrics || {}
    return { name, 收益: m.total_return, 年化: m.cagr, 夏普: m.sharpe, α: m.alpha, β: m.beta, γ: m.gamma, 胜率: m.win_rate, 交易: m.num_trades }
  })
  return arr.sort((a, b) => (b.收益 || 0) - (a.收益 || 0))
})

const fmtPct = (v: unknown) => typeof v === 'number' ? (v >= 0 ? '+' : '') + (v * 100).toFixed(2) + '%' : '—'
const fmtNum = (v: unknown, d = 2) => typeof v === 'number' ? v.toFixed(d) : '—'
</script>

<template>
  <div class="research">
    <PageHeader title="研究" subtitle="市场环境 · 因子研究 · 策略回测" />

    <!-- 市场环境条 -->
    <section class="sec">
      <h2 class="sec-title"><Icon name="market" :size="18" /> 市场环境判断</h2>
      <Skeleton v-if="regimeLoading && !regime" />
      <Card v-else-if="regime" highlight>
        <div class="regime-grid">
          <div class="regime-main">
            <div class="regime-label muted">当前环境</div>
            <div :class="['regime-val', 'num', regimeColor(regime.regime)]">{{ regime.regime_cn }}</div>
            <div class="regime-sub muted">推荐策略：{{ regime.suggest_strategy }}</div>
            <div v-if="regime.rotation" class="regime-rot">
              <span class="rot-badge gold">主策略</span>
              <span class="rot-name">{{ (regime.rotation as Record<string, unknown>).primary }}</span>
              <span class="rot-basis muted">{{ (regime.rotation as Record<string, unknown>).basis }}</span>
            </div>
          </div>
          <div class="regime-meta">
            <div class="meta-row" v-if="regime.score"><span class="meta-k">MA20</span><span class="meta-v num">{{ (regime.score as Record<string, unknown>).ma20 }}</span></div>
            <div class="meta-row" v-if="regime.score"><span class="meta-k">MA60</span><span class="meta-v num">{{ (regime.score as Record<string, unknown>).ma60 }}</span></div>
            <div class="meta-row" v-if="regime.sys_risk"><span class="meta-k">系统风险</span><span :class="['meta-v', 'num', (regime.sys_risk as Record<string, unknown>).triggered ? 'up' : 'down']">{{ (regime.sys_risk as Record<string, unknown>).triggered ? '已触发' : '正常' }}</span></div>
            <div class="meta-row"><span class="meta-k">数据至</span><span class="meta-v muted">{{ regime.as_of }}</span></div>
          </div>
        </div>
      </Card>
      <EmptyState v-else-if="!regimeLoading" message="无法获取市场环境数据" />
    </section>

    <!-- 页签交互 -->
    <section class="sec">
      <div class="tabbar">
        <button v-for="t in tabs" :key="t.id" :class="['tab', { active: tab === t.id }]" @click="tab = t.id">
          <Icon :name="t.icon" :size="15" /> {{ t.label }}
        </button>
      </div>

      <!-- ① 策略回测 -->
      <div v-if="tab === 'backtest'" class="tabpanel">
        <Card>
          <div class="bt-toolbar">
            <select v-model="btContractName" class="sel">
              <option v-for="s in strategies" :key="s.id" :value="s.name">{{ s.name }}</option>
            </select>
            <input v-model="btStart" class="inp" placeholder="起始" />
            <input v-model="btEnd" class="inp" placeholder="结束" />
            <button class="btn" :disabled="btRunning" @click="doBacktest">
              <Icon v-if="btRunning" name="refresh" :size="14" class="spin" />
              {{ btRunning ? '回测中…' : '开始回测' }}
            </button>
          </div>
        </Card>

        <template v-if="btResult">
          <div class="bt-metrics">
            <StatCard label="总收益" :value="fmtPct(btResult.metrics.total_return)" :trend="(btResult.metrics.total_return||0)>=0?'up':'down'" />
            <StatCard label="年化" :value="fmtPct(btResult.metrics.cagr)" />
            <StatCard label="夏普" :value="fmtNum(btResult.metrics.sharpe)" />
            <StatCard label="最大回撤" :value="fmtPct(btResult.metrics.max_drawdown)" :trend="'down'" />
            <StatCard label="阿尔法" :value="fmtPct(btResult.metrics.alpha)" />
            <StatCard label="贝塔" :value="fmtNum(btResult.metrics.beta)" />
            <StatCard label="伽马(信息比)" :value="fmtNum(btResult.metrics.gamma)" />
            <StatCard label="胜率" :value="fmtPct(btResult.metrics.win_rate)" />
            <StatCard label="交易次数" :value="String(btResult.metrics.num_trades ?? '—')" />
            <StatCard label="年换手" :value="fmtNum(btResult.metrics.turnover_yearly)" />
          </div>
          <Card class="mt"><div ref="btChartEl" class="chart"></div></Card>
        </template>
        <EmptyState v-else-if="!btRunning" message="选择策略后点击「开始回测」查看完整指标与净值" />
      </div>

      <!-- ② 因子研究 -->
      <div v-if="tab === 'study'" class="tabpanel">
        <Card>
          <div class="bt-toolbar">
            <select v-model="studyFactor" class="sel">
              <option v-for="f in factors" :key="f.id" :value="f.id">{{ f.name }} ({{ f.id }})</option>
            </select>
            <button class="btn" :disabled="studyRunning" @click="doStudy">
              <Icon v-if="studyRunning" name="refresh" :size="14" class="spin" />
              {{ studyRunning ? '研究中…' : '因子研究' }}
            </button>
          </div>
        </Card>
        <Card v-if="studyResult" class="mt">
          <pre class="study-out">{{ JSON.stringify(studyResult, null, 2) }}</pre>
        </Card>
        <EmptyState v-else-if="!studyRunning" message="选择因子后「因子研究」查看 IC/ICIR 与分组收益" />
      </div>

      <!-- ③ 策略对比 -->
      <div v-if="tab === 'compare'" class="tabpanel">
        <Card>
          <div class="bt-toolbar">
            <button class="btn" :disabled="cmpRunning" @click="doCompare">
              <Icon v-if="cmpRunning" name="refresh" :size="14" class="spin" />
              {{ cmpRunning ? '对比中…' : '对比5策略' }}
            </button>
            <span class="muted hint">2024-01 → 2026-08 完整买卖, 含 α/β/γ/胜率/交易</span>
          </div>
        </Card>
        <Card v-if="cmpRows.length" class="mt">
          <table class="tbl">
            <thead><tr><th>策略</th><th class="ar">收益</th><th class="ar">夏普</th><th class="ar">α</th><th class="ar">β</th><th class="ar">γ</th><th class="ar">胜率</th><th class="ar">交易</th></tr></thead>
            <tbody>
              <tr v-for="r in cmpRows" :key="r.name">
                <td class="strat">{{ r.name }}</td>
                <td class="ar num" :class="(r.收益||0)>=0?'up':'down'">{{ fmtPct(r.收益) }}</td>
                <td class="ar num">{{ fmtNum(r.夏普) }}</td>
                <td class="ar num">{{ fmtPct(r.α) }}</td>
                <td class="ar num">{{ fmtNum(r.β) }}</td>
                <td class="ar num">{{ fmtNum(r.γ) }}</td>
                <td class="ar num">{{ fmtPct(r.胜率) }}</td>
                <td class="ar num">{{ r.交易 ?? '—' }}</td>
              </tr>
            </tbody>
          </table>
        </Card>
        <EmptyState v-else-if="!cmpRunning" message="点击「对比5策略」查看横向对比" />
      </div>
    </section>

    <!-- 因子库/策略库 (收起, 保持单页不过多信息) -->
    <details class="sec refs">
      <summary class="refs-summary muted">因子库 / 策略库参考</summary>
      <div class="factor-grid" v-if="factors.length">
        <Card v-for="f in factors" :key="f.id" padding>
          <div class="factor-hd"><span class="factor-id">{{ f.id }}</span><span class="factor-group">{{ f.group }}</span></div>
          <div class="factor-name">{{ f.name }}</div>
          <div class="factor-desc muted">{{ f.desc }}</div>
        </Card>
      </div>
      <div class="strat-list" v-if="strategies.length">
        <Card v-for="s in strategies" :key="s.id" padding highlight>
          <div class="strat-hd"><span class="strat-name gold">{{ s.name }}</span><span class="strat-kind">{{ s.kind === 'multi_factor' ? '多因子' : s.kind }}</span></div>
          <div class="strat-desc">{{ s.desc }}</div>
          <div class="strat-meta muted">因子: {{ s.factors.join(' + ') }} · 持仓{{ s.rebalance_bars }}日 · Top {{ (s.top_k_pct * 100).toFixed(0) }}%</div>
        </Card>
      </div>
    </details>
  </div>
</template>

<style scoped>
.research { max-width: 1080px; }
.sec { margin-bottom: var(--sp-6); }
.sec-title { font-size: var(--fs-lg); font-weight: 600; color: var(--text); margin: 0 0 var(--sp-4); display: flex; align-items: center; gap: var(--sp-2); }
.regime-grid { display: flex; gap: var(--sp-8); align-items: center; }
.regime-main { flex: 1; }
.regime-label { font-size: var(--fs-sm); margin-bottom: 2px; }
.regime-val { font-size: var(--fs-hero); font-weight: 800; margin: var(--sp-1) 0; }
.regime-sub { font-size: var(--fs-md); color: var(--text-sub); }
.regime-rot { display: flex; align-items: center; gap: var(--sp-2); margin-top: var(--sp-2); flex-wrap: wrap; }
.rot-badge { font-size: var(--fs-xs); border: 1px solid var(--gold); color: var(--gold); padding: 1px 7px; border-radius: var(--radius-pill); }
.rot-name { font-size: var(--fs-md); font-weight: 700; color: var(--gold); }
.rot-basis { font-size: var(--fs-sm); }
.regime-meta { display: flex; flex-direction: column; gap: var(--sp-2); }
.meta-row { display: flex; justify-content: space-between; gap: var(--sp-4); }
.meta-k { color: var(--text-sub); font-size: var(--fs-sm); min-width: 60px; }
.meta-v { font-size: var(--fs-md); font-weight: 500; }
.tabbar { display: flex; gap: var(--sp-1); border-bottom: 1px solid var(--border); margin-bottom: var(--sp-4); }
.tab { display: inline-flex; align-items: center; gap: var(--sp-1); padding: 9px 16px; border: none; background: transparent; color: var(--text-sub); font-size: var(--fs-sm); font-weight: 600; cursor: pointer; border-bottom: 2px solid transparent; transition: color var(--dur-fast); }
.tab:hover { color: var(--text); }
.tab.active { color: var(--gold); border-bottom-color: var(--gold); }
.bt-toolbar { display: flex; align-items: center; gap: var(--sp-2); flex-wrap: wrap; }
.sel, .inp { background: var(--bg); border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 8px 10px; color: var(--text); font-size: var(--fs-sm); }
.sel:focus, .inp:focus { border-color: var(--gold); outline: none; }
.btn { display: inline-flex; align-items: center; gap: var(--sp-1); padding: 8px 16px; border: none; border-radius: var(--radius-sm); background: var(--gold); color: #fff; font-weight: 700; font-size: var(--fs-sm); cursor: pointer; }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.hint { font-size: var(--fs-xs); }
.bt-metrics { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: var(--sp-3); margin-top: var(--sp-4); }
.mt { margin-top: var(--sp-4); }
.chart { height: 300px; }
.tbl { width: 100%; border-collapse: collapse; font-size: var(--fs-sm); }
.tbl th { padding: 10px var(--sp-3); text-align: left; color: var(--text-sub); border-bottom: 1px solid var(--border); }
.tbl .ar { text-align: right; }
.tbl tr:hover { background: var(--bg-hover); }
.tbl td { padding: 10px var(--sp-3); border-bottom: 1px solid var(--border-soft); }
.strat { font-weight: 600; }
.num { font-family: var(--font-mono); }
.study-out { white-space: pre-wrap; font-size: var(--fs-xs); color: var(--text-sub); max-height: 480px; overflow: auto; }
.refs-summary { cursor: pointer; padding: var(--sp-2) 0; list-style: none; }
.factor-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: var(--sp-3); margin-top: var(--sp-3); }
.factor-hd { display: flex; justify-content: space-between; align-items: center; margin-bottom: var(--sp-1); }
.factor-id { font-family: var(--font-mono); font-size: var(--fs-sm); color: var(--accent); font-weight: 600; }
.factor-group { font-size: var(--fs-xs); color: var(--text-faint); border: 1px solid var(--border); padding: 1px 6px; border-radius: var(--radius-pill); }
.factor-name { font-size: var(--fs-md); font-weight: 600; }
.factor-desc { font-size: var(--fs-sm); line-height: 1.4; }
.strat-list { display: flex; flex-direction: column; gap: var(--sp-3); margin-top: var(--sp-3); }
.strat-hd { display: flex; align-items: center; gap: var(--sp-3); margin-bottom: var(--sp-1); }
.strat-name { font-size: var(--fs-lg); font-weight: 700; }
.strat-kind { font-size: var(--fs-xs); color: var(--text-faint); border: 1px solid var(--border); padding: 1px 6px; border-radius: var(--radius-pill); }
.strat-desc { font-size: var(--fs-md); color: var(--text-sub); }
.strat-meta { font-size: var(--fs-sm); }
.gold { color: var(--gold); }
.muted { color: var(--text-faint); }
.up { color: var(--up); } .down { color: var(--down); } .flat { color: var(--text-faint); }
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
