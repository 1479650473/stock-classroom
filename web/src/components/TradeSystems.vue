<script setup lang="ts">
/**
 * 三大程序交易体系总览（交易页首屏）。
 *
 * 三个体系原理不同，必须明确区分：
 *   体系一 固定策略   —— 因子公式写定交易规则，程序机械执行（本项目 · 策略页）
 *   体系二 外部 LLM   —— 大模型逐日推理决策买卖（本项目 · AI 页）
 *   体系三 本地模型   —— 本地训练出来的预测模型驱动交易（stock-ml · 本页「模拟盘」页签）
 */
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { getPaperPortfolio, getTraderOverview, getSimAccounts } from '@/api'
import type { PaperPortfolio, TraderOverview, SimSnapshot } from '@/api'

const emit = defineEmits<{ go: [tab: string] }>()
const router = useRouter()

const paper1 = ref<PaperPortfolio | null>(null)
const paper2 = ref<PaperPortfolio | null>(null)
const traders = ref<TraderOverview | null>(null)
const sim = ref<SimSnapshot | null>(null)
const failed = ref<Record<string, boolean>>({})

onMounted(async () => {
  const [p1, p2, t, s] = await Promise.allSettled([
    getPaperPortfolio(''),
    getPaperPortfolio('rank2'),
    getTraderOverview(),
    getSimAccounts(),
  ])
  if (p1.status === 'fulfilled') paper1.value = p1.value; else failed.value.paper1 = true
  if (p2.status === 'fulfilled') paper2.value = p2.value; else failed.value.paper2 = true
  if (t.status === 'fulfilled') traders.value = t.value; else failed.value.traders = true
  if (s.status === 'fulfilled') sim.value = s.value; else failed.value.sim = true
})

function fmt(n: number | undefined | null, digits = 0): string {
  if (n === undefined || n === null || !Number.isFinite(n)) return '—'
  return n.toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits })
}
function fmtDate(s: string | undefined | null): string {
  if (!s) return '—'
  const t = String(s)
  return /^\d{8}$/.test(t) ? `${t.slice(0, 4)}-${t.slice(4, 6)}-${t.slice(6, 8)}` : t
}
function signedPct(n: number | undefined | null, digits = 2): string {
  if (n === undefined || n === null || !Number.isFinite(n)) return '—'
  return (n >= 0 ? '+' : '') + n.toFixed(digits) + '%'
}

const enabledTraders = () => (traders.value?.traders || []).filter((t) => t.enabled)
function traderNav(t: { nav: { nav: number }[] }): number | null {
  const last = t.nav?.[t.nav.length - 1]
  return last ? last.nav : null
}
const simTop = () => sim.value?.accounts?.[0] || null
const simSum = () => {
  const list = sim.value?.accounts || []
  if (!list.length) return null
  const avg = list.reduce((s, a) => s + (Number(a.ret_pct) || 0), 0) / list.length
  return avg
}
</script>

<template>
  <div class="sys-wrap">
    <div class="sys-intro">
      以下是本项目并行的 <b>三个程序交易体系</b>，原理与口径各不相同：固定策略按公式机械执行、
      外部 LLM 逐日推理决策、本地预测模型（stock-ml）驱动。三者各自独立记录、互不影响。
    </div>

    <div class="sys-grid">
      <!-- 体系一 -->
      <div class="sys-card sys-card--one">
        <div class="sys-card__head">
          <span class="sys-card__tag">体系一</span>
          <span class="sys-card__kind">固定策略</span>
        </div>
        <div class="sys-card__title">因子公式 · 机械执行</div>
        <p class="sys-card__principle">按因子公式写定交易规则，程序每日按分数排序、机械调仓 —— 不预测未来、不做解释。</p>
        <div class="sys-card__body">
          <div class="sys-kv">
            <span>组合纸面盘 v1（等权）</span>
            <b>
              {{ fmt(paper1?.nav, 4) }}
              <i :class="(paper1?.total_return_pct ?? 0) >= 0 ? 'up' : 'down'">{{ signedPct(paper1?.total_return_pct) }}</i>
            </b>
          </div>
          <div class="sys-kv">
            <span>组合纸面盘 v2（rank2 加权）</span>
            <b>
              {{ fmt(paper2?.nav, 4) }}
              <i :class="(paper2?.total_return_pct ?? 0) >= 0 ? 'up' : 'down'">{{ signedPct(paper2?.total_return_pct) }}</i>
            </b>
          </div>
          <div class="sys-kv sys-kv--muted">
            <span>运行天数 / 起始</span>
            <b>{{ fmt(paper1?.days) }} 天 · {{ fmtDate(paper1?.created_at) }}</b>
          </div>
        </div>
        <div class="sys-card__foot">
          <span class="sys-card__where">策略页 · 因子挖掘 · 组合纸面盘</span>
          <button class="ui-btn ui-btn--sm" @click="router.push({ path: '/strategy', query: { tab: 'alpha' } })">
            查看详情
          </button>
        </div>
      </div>

      <!-- 体系二 -->
      <div class="sys-card sys-card--two">
        <div class="sys-card__head">
          <span class="sys-card__tag">体系二</span>
          <span class="sys-card__kind">外部 LLM 决策</span>
        </div>
        <div class="sys-card__title">大模型逐日推理</div>
        <p class="sys-card__principle">由外部大模型扮演交易员逐日推理买卖（含工具调用、自我复盘），规则由系统强制、模型自由发挥。</p>
        <div class="sys-card__body">
          <div class="sys-kv">
            <span>交易员 / 启用</span>
            <b>{{ (traders?.traders || []).length }} 位 · 启用 {{ enabledTraders().length }}</b>
          </div>
          <div v-for="t in enabledTraders().slice(0, 3)" :key="t.profile_id" class="sys-kv">
            <span>{{ t.name }}</span>
            <b>{{ traderNav(t) ? traderNav(t)!.toFixed(4) + '×' : '—' }}</b>
          </div>
          <div class="sys-kv sys-kv--muted">
            <span>基准</span>
            <b>{{ traders?.benchmark?.name || '沪深300' }}</b>
          </div>
        </div>
        <div class="sys-card__foot">
          <span class="sys-card__where">AI 页 · AI 操盘手</span>
          <button class="ui-btn ui-btn--sm" @click="router.push({ path: '/ai', query: { tab: 'trader' } })">
            查看详情
          </button>
        </div>
      </div>

      <!-- 体系三 -->
      <div class="sys-card sys-card--three">
        <div class="sys-card__head">
          <span class="sys-card__tag">体系三</span>
          <span class="sys-card__kind">本地预测模型</span>
        </div>
        <div class="sys-card__title">本地训练模型驱动</div>
        <p class="sys-card__principle">由 stock-ml 项目里<b>本地训练出来的预测模型</b>给出信号、驱动策略账户；快照同步到本项目查看。</p>
        <div class="sys-card__body">
          <div class="sys-kv">
            <span>模拟账户</span>
            <b>{{ (sim?.accounts || []).length }} 个</b>
          </div>
          <div class="sys-kv">
            <span>{{ simTop()?.label || '主账户' }}</span>
            <b>
              {{ fmt(simTop()?.nav, 2) }}
              <i :class="(simTop()?.ret_pct ?? 0) >= 0 ? 'up' : 'down'">{{ signedPct(simTop()?.ret_pct) }}</i>
            </b>
          </div>
          <div class="sys-kv sys-kv--muted">
            <span>各账户平均收益</span>
            <b>{{ signedPct(simSum()) }}</b>
          </div>
        </div>
        <div class="sys-card__foot">
          <span class="sys-card__where">本页 · 模拟盘页签</span>
          <button class="ui-btn ui-btn--sm ui-btn--primary" @click="emit('go', 'sim')">
            查看详情
          </button>
        </div>
      </div>
    </div>

    <!-- 对照表 -->
    <div class="sys-table-wrap">
      <table class="sys-table">
        <thead>
          <tr>
            <th>对比</th>
            <th>体系一 · 固定策略</th>
            <th>体系二 · 外部 LLM</th>
            <th>体系三 · 本地预测模型</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>决策依据</td>
            <td>因子公式得分（程序算出，规则写死）</td>
            <td>大模型逐日推理（工具调用 + 自我复盘）</td>
            <td>本地训练模型输出的预测/信号</td>
          </tr>
          <tr>
            <td>会不会预测</td>
            <td>不预测，只排序与调仓</td>
            <td>会（方向预测可弃权，且有校准）</td>
            <td>会（模型打分即预测）</td>
          </tr>
          <tr>
            <td>决策频率</td>
            <td>每日 1/H 分仓、机械轮动</td>
            <td>每交易日一次决策</td>
            <td>随信号触发</td>
          </tr>
          <tr>
            <td>运行位置</td>
            <td>本项目 · 策略页</td>
            <td>本项目 · AI 页</td>
            <td>stock-ml 项目 · 本页同步查看</td>
          </tr>
          <tr>
            <td>决策留档</td>
            <td>前瞻记录（不可回看、不可调参）</td>
            <td>每笔含思考过程 / 工具轨迹 / 复盘</td>
            <td>外部快照（由 stock-ml 生成）</td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-if="Object.keys(failed).length" class="sys-warn">
      部分数据源未就绪：{{ Object.keys(failed).join(' / ') }}（不影响其他体系）
    </div>
  </div>
</template>

<style scoped>
.sys-wrap { display: flex; flex-direction: column; gap: var(--sp-4); padding: var(--sp-4) var(--sp-5) var(--sp-5); }

.sys-intro {
  font-size: var(--fs-sm);
  color: var(--text-sub);
  line-height: 1.7;
}
.sys-intro b { color: var(--text); }

.sys-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: var(--sp-4); }

.sys-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 16px 18px 14px;
  border-radius: var(--radius-lg);
  border: 1px solid var(--border-soft);
  background: linear-gradient(180deg, var(--bg-raised), var(--bg-panel));
  transition: border-color var(--dur-fast) var(--ease), transform var(--dur) var(--ease);
}
.sys-card:hover { transform: translateY(-2px); }
.sys-card--one:hover { border-color: var(--gold); }
.sys-card--two:hover { border-color: var(--accent); }
.sys-card--three:hover { border-color: var(--ok); }

.sys-card__head { display: flex; align-items: center; gap: 8px; }
.sys-card__tag {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.06em;
  padding: 2px 8px;
  border-radius: var(--radius-pill);
  border: 1px solid currentColor;
}
.sys-card--one .sys-card__tag { color: var(--gold); }
.sys-card--two .sys-card__tag { color: var(--accent); }
.sys-card--three .sys-card__tag { color: var(--ok); }
.sys-card__kind { font-size: 12px; color: var(--text-faint); }

.sys-card__title { font-size: var(--fs-lg); font-weight: 650; color: var(--text); }
.sys-card__principle { margin: 0; font-size: var(--fs-sm); color: var(--text-sub); line-height: 1.65; min-height: 44px; }
.sys-card__principle b { color: var(--text); }

.sys-card__body {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 10px 12px;
  border-radius: var(--radius-md);
  background: var(--bg-panel);
  border: 1px solid var(--border-soft);
}
.sys-kv { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; font-size: var(--fs-sm); }
.sys-kv > span { color: var(--text-sub); min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sys-kv > b { color: var(--text); font-weight: 600; font-variant-numeric: tabular-nums; white-space: nowrap; }
.sys-kv > b i { font-style: normal; font-weight: 600; margin-left: 6px; }
.sys-kv--muted > span,
.sys-kv--muted > b { color: var(--text-faint); font-weight: 500; }

.sys-card__foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-top: auto;
  padding-top: 10px;
  border-top: 1px dashed var(--border);
}
.sys-card__where { font-size: 11px; color: var(--text-faint); }

.sys-table-wrap { overflow-x: auto; border: 1px solid var(--border-soft); border-radius: var(--radius-lg); }
.sys-table { width: 100%; border-collapse: collapse; font-size: var(--fs-sm); }
.sys-table th,
.sys-table td { padding: 9px 14px; text-align: left; border-bottom: 1px solid var(--border-soft); }
.sys-table tr:last-child td { border-bottom: none; }
.sys-table thead th {
  color: var(--text-sub);
  font-weight: 600;
  background: var(--bg-raised);
  white-space: nowrap;
}
.sys-table td:first-child { color: var(--text-faint); white-space: nowrap; }
.sys-table td { color: var(--text); }
.sys-table tbody tr:hover { background: var(--bg-hover); }

.sys-warn { font-size: var(--fs-xs); color: var(--text-faint); }

.up { color: var(--up); }
.down { color: var(--down); }

.ui-btn--sm { padding: 5px 12px; font-size: 12px; }
</style>
