<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import Icon from '@/components/Icon.vue'
import { getLiveAccount, queryLivePanel, type LiveAccountResult } from '@/api'
import { useToastStore } from '@/stores/toast'

/**
 * 账户总览（实盘页顶部）—— 打开就能看到，不用先点"读取"。
 *
 * ## 为什么要这个组件
 * 券商客户端的面板读取靠 OCR：慢（9~13s）、且**必须客户端已登录**。
 * 原来打开实盘页是一片空白 + 四个"读取"按钮，主次颠倒 ——
 * 用户最想先看到的"我现在有多少钱、持了什么"反而要手动点。
 *
 * ## 数据从哪来（按可信度）
 * 1. **AUTO_LOG.md** —— 策略侧**人工核对过**的账户读数，数字干净且带日期
 * 2. **最新快照** —— 只取 `funds_value` / `max_buy_value` 这类**干净浮点字段**
 * 3. 实时读取（客户端在线时，由「刷新账户」触发）
 *
 * ## 三条展示纪律
 * 1. **必须显示时间**：每个数字旁边都有 `as_of`，陈旧就标陈旧（"N 天前"）。
 * 2. **不跨时点混算**：主读数与收盘读数是**两个时点**，分开显示，绝不加总。
 * 3. **读不到就说读不到**：不能把"解析失败"显示成"空仓/0 元"。
 */
const toast = useToastStore()

const data = ref<LiveAccountResult | null>(null)
const loading = ref(true)
const error = ref('')
const refreshing = ref(false)

async function load(silent = false) {
  if (!silent) loading.value = true
  error.value = ''
  try {
    data.value = await getLiveAccount()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '账户数据加载失败'
  } finally {
    loading.value = false
  }
}

onMounted(() => { void load() })

const est = computed(() => data.value?.estimate)
const hasEst = computed(() => !!est.value?.available)

/** 距 as_of 多少天（陈旧提示）。日期解析失败返回 null，不猜。 */
const staleDays = computed<number | null>(() => {
  const d = est.value?.as_of
  if (!d) return null
  const t = Date.parse(`${d}T00:00:00`)
  if (Number.isNaN(t)) return null
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  return Math.max(0, Math.round((today - t) / 86400000))
})

const staleText = computed(() => {
  const n = staleDays.value
  if (n == null) return ''
  if (n === 0) return '今天'
  return `${n} 天前`
})

/** 陈旧阈值：非今天即提示（交易账户数据按日变化，隔日就该提醒） */
const isStale = computed(() => (staleDays.value ?? 0) > 0)

function money(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return '—'
  return v.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function signed(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return '—'
  return (v >= 0 ? '+' : '') + money(v)
}

const pnlPct = computed(() => {
  const p = est.value?.float_pnl
  const c = est.value?.cost
  const q = est.value?.qty
  if (p == null || c == null || q == null || c * q === 0) return null
  return (p / (c * q)) * 100
})

const posLabel = computed(() => {
  const e = est.value
  if (!e?.code) return null
  return { code: e.code, name: e.name || e.code, qty: e.qty, cost: e.cost, price: e.price }
})

/**
 * 成本**必须显示 4 位小数**（4.6772）。
 *
 * ⚠️ 这里踩过一次：原来用时 `money()`（2 位）显示成 `4.68`，
 * 用户按 `700 × 4.68 = 3276`、`3304 − 3276 = 28` 去对，与显示的浮盈 `+29.97` **差 1.97**，
 * 于是判"账户对不上"。**1 分钱的显示精度在成本价上会被放大成近 2 元**。
 * 成本价一律 4 位，并额外给出「成本额」让用户能直接验算。
 */
function cost4(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return '—'
  return v.toFixed(4)
}

/** 成本额 = 数量 × 成本价（供用户验算：市值 − 成本额 = 浮盈） */
const costAmount = computed<number | null>(() => {
  const e = est.value
  if (e?.qty == null || e?.cost == null) return null
  return e.qty * e.cost
})

/** 持仓明细一行（派生自同一条读数，保证与上方数字同源同口径） */
const posRow = computed(() => {
  const e = est.value
  if (!e?.code) return null
  return {
    code: e.code,
    name: e.name || e.code,
    qty: e.qty,
    cost: e.cost,
    price: e.price,
    costAmount: costAmount.value,
    marketValue: e.market_value,
    pnl: e.float_pnl,
    pnlPct: pnlPct.value,
  }
})

/** 自校验失败项（非空即警示 —— 数据自相矛盾时不能静默展示） */
const badChecks = computed(() => {
  const c = est.value?.checks
  if (!c) return []
  return Object.entries(c)
    .filter(([, v]) => v && v.ok === false)
    .map(([k, v]) => ({ key: k, formula: v.formula ?? '', diff: v.diff }))
})

/** 收盘浮盈（与盘前分开，绝不混算） */
const closePnl = computed(() => est.value?.close?.float_pnl ?? null)

/**
 * 刷新账户：客户端**只能一次读一个面板**，所以先读资金、再读持仓。
 * 失败不隐瞒 —— 把工具原话带出来（未登录/未打开时它会给明确原因）。
 */
async function doRefresh() {
  refreshing.value = true
  try {
    const [funds, positions] = await Promise.allSettled([
      queryLivePanel('funds', true),
      queryLivePanel('positions', true),
    ])
    const f = funds.status === 'fulfilled' ? funds.value : null
    const p = positions.status === 'fulfilled' ? positions.value : null
    const okAny = (f?.ok || p?.ok)
    if (okAny) {
      toast.success('账户已刷新')
      await load(true)
    } else {
      const msg = f?.result?.message || p?.result?.message || f?.error || p?.error || '读取失败'
      toast.error('客户端读取失败：' + msg)
    }
  } catch (e) {
    toast.error('刷新失败：' + (e instanceof Error ? e.message : String(e)))
  } finally {
    refreshing.value = false
  }
}
</script>

<template>
  <section class="acct" :class="{ 'acct--stale': isStale }">
    <!-- 顶部：持仓身份 + 刷新 -->
    <header class="acct__hd">
      <div class="acct__id">
        <template v-if="posLabel">
          <span class="acct__code mono">{{ posLabel.code }}</span>
          <b class="acct__name">{{ posLabel.name }}</b>
          <span class="acct__qty">{{ posLabel.qty }} 股</span>
          <span v-if="posLabel.cost != null" class="acct__cost">成本 {{ cost4(posLabel.cost) }}</span>
        </template>
        <template v-else-if="loading">
          <span class="acct__name">读取账户…</span>
        </template>
        <template v-else>
          <span class="acct__name acct__name--empty">账户读数不可用</span>
        </template>
      </div>

      <div class="acct__actions">
        <span class="acct__dot" :class="data?.readable ? 'is-ok' : 'is-off'"
              :title="data?.readable ? '券商客户端当前可读' : '券商客户端当前不可读（未登录/未打开）'" />
        <span class="acct__dot-label">{{ data?.readable ? '客户端在线' : '客户端离线' }}</span>
        <button class="ui-btn ui-btn--sm" :disabled="refreshing" @click="doRefresh">
          <Icon :name="refreshing ? 'refresh' : 'download'" :size="13"
                :class="{ spin: refreshing }" />
          {{ refreshing ? '读取中…' : '刷新账户' }}
        </button>
      </div>
    </header>

    <!-- 数字区 -->
    <div v-if="hasEst" class="acct__grid">
      <div class="acct__cell">
        <span class="acct__k">总资产</span>
        <b class="acct__v">{{ money(est?.total_assets) }}</b>
        <span v-if="est?.close?.total_assets != null" class="acct__sub">
          收盘 {{ money(est.close.total_assets) }}
        </span>
        <span v-else class="acct__sub acct__sub--ghost">—</span>
      </div>

      <div class="acct__cell">
        <span class="acct__k">可用资金</span>
        <b class="acct__v">{{ money(est?.cash) }}</b>
        <span class="acct__sub acct__sub--ghost">可买上限</span>
      </div>

      <div class="acct__cell">
        <span class="acct__k">持仓市值</span>
        <b class="acct__v">{{ money(est?.market_value) }}</b>
        <span v-if="est?.close?.market_value != null" class="acct__sub">
          收盘 {{ money(est.close.market_value) }}
        </span>
        <span v-else class="acct__sub acct__sub--ghost">—</span>
      </div>

      <div class="acct__cell">
        <span class="acct__k">持仓浮盈</span>
        <b class="acct__v" :class="(est?.float_pnl ?? 0) >= 0 ? 'up' : 'down'">
          {{ signed(est?.float_pnl) }}
        </b>
        <!-- 收盘浮盈必须也给出来：否则用户会拿「收盘市值」配「盘前浮盈」，怎么算都对不上 -->
        <span class="acct__sub">
          <template v-if="closePnl != null">
            收盘 <b :class="closePnl >= 0 ? 'up' : 'down'">{{ signed(closePnl) }}</b>
          </template>
          <template v-else-if="pnlPct != null" :class="(est?.float_pnl ?? 0) >= 0 ? 'up' : 'down'">
            {{ pnlPct >= 0 ? '+' : '' }}{{ pnlPct.toFixed(2) }}%
          </template>
          <template v-else>—</template>
        </span>
      </div>
    </div>

    <!-- 无读数：说清原因，不伪造 0 -->
    <div v-else-if="!loading" class="acct__empty">
      <Icon name="alert" :size="14" />
      <span>{{ error || est?.reason || '暂无账户读数。客户端在线时点「刷新账户」读取。' }}</span>
    </div>

    <!-- 自校验失败警示：数据自相矛盾时必须让人看见，不能静默展示错误数字 -->
    <div v-if="badChecks.length" class="acct__warn">
      <Icon name="alert" :size="14" />
      <div>
        <b>账户数据自校验未通过</b>（下面的数字可能不可靠）：
        <span v-for="(c, i) in badChecks" :key="c.key" class="acct__warn-item">
          {{ i ? '；' : '' }}{{ c.formula || c.key }}<template v-if="c.diff != null">，差 {{ c.diff }}</template>
        </span>
      </div>
    </div>

    <!-- 持仓明细：一行一只票，并给出「成本额」让用户能直接验算 -->
    <div v-if="hasEst && posRow" class="acct__pos">
      <table class="acct__tbl">
        <thead>
          <tr>
            <th>代码</th><th>名称</th><th class="r">数量</th>
            <th class="r">成本价</th><th class="r">成本额</th>
            <th class="r">现价</th><th class="r">市值</th><th class="r">浮盈</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td class="mono">{{ posRow.code }}</td>
            <td>{{ posRow.name }}</td>
            <td class="r">{{ posRow.qty ?? '—' }}</td>
            <td class="r mono">{{ cost4(posRow.cost) }}</td>
            <td class="r mono">{{ money(posRow.costAmount) }}</td>
            <td class="r">{{ money(posRow.price) }}</td>
            <td class="r mono">{{ money(posRow.marketValue) }}</td>
            <td class="r" :class="(posRow.pnl ?? 0) >= 0 ? 'up' : 'down'">
              {{ signed(posRow.pnl) }}
              <span v-if="posRow.pnlPct != null" class="acct__pct">
                ({{ posRow.pnlPct >= 0 ? '+' : '' }}{{ posRow.pnlPct.toFixed(2) }}%)
              </span>
            </td>
          </tr>
        </tbody>
      </table>
      <!-- 把验算式直接写出来，省得用户自己找差在哪 -->
      <p v-if="posRow.costAmount != null && posRow.marketValue != null && posRow.pnl != null" class="acct__verify">
        验算：市值 {{ money(posRow.marketValue) }} − 成本额 {{ money(posRow.costAmount) }}
        = <b>{{ signed(posRow.marketValue - posRow.costAmount) }}</b>
        <span class="acct__verify-note">（与浮盈 {{ signed(posRow.pnl) }} 相差
          {{ Math.abs((posRow.marketValue - posRow.costAmount) - posRow.pnl).toFixed(2) }}，属分位取整）</span>
      </p>
    </div>

    <!-- 底部：数据来源与时间（诚实标注，这是本组件的核心纪律） -->
    <footer v-if="hasEst" class="acct__ft">
      <span class="acct__src">
        <Icon name="info" :size="12" />
        数据：<b>{{ est?.as_of || '日期未知' }}</b>
        <span v-if="staleText" :class="{ 'acct__stale': isStale }">（{{ staleText }}）</span>
        · {{ est?.source || '来源未知' }}
      </span>
      <span v-if="est?.carried_over" class="acct__note">含"沿用核对值"的条目</span>
      <span v-if="est?.close" class="acct__note">收盘数据另列，不与盘前混算</span>
    </footer>
  </section>
</template>

<style scoped>
/* 账户总览：整页最上、最醒目的一块。做成"卡片头"，与下方功能卡片区分层级。 */
.acct {
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  background: linear-gradient(180deg, var(--bg-panel), var(--bg-panel-2, var(--bg-panel)));
  overflow: hidden;
}
/* 陈旧时给左侧一条黄边 —— 不喧哗但一定能看到 */
.acct--stale { border-left: 3px solid var(--warn); }

.acct__hd {
  display: flex; align-items: center; justify-content: space-between;
  gap: var(--sp-3); flex-wrap: wrap;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-soft);
}
.acct__id { display: flex; align-items: baseline; gap: 9px; flex-wrap: wrap; }
.acct__code { font-size: var(--fs-sm); color: var(--text-sub); }
.acct__name { font-size: var(--fs-lg); color: var(--text); letter-spacing: .2px; }
.acct__name--empty { color: var(--text-faint); font-size: var(--fs-md); }
.acct__qty { font-size: var(--fs-sm); color: var(--text-sub); }
.acct__cost { font-size: var(--fs-sm); color: var(--text-faint); }

.acct__actions { display: flex; align-items: center; gap: 8px; }
.acct__dot { width: 7px; height: 7px; border-radius: 50%; display: inline-block; }
.acct__dot.is-ok { background: var(--ok); box-shadow: 0 0 0 3px color-mix(in srgb, var(--ok) 18%, transparent); }
.acct__dot.is-off { background: var(--text-faint); }
.acct__dot-label { font-size: var(--fs-xs); color: var(--text-faint); }

.acct__grid {
  display: grid; grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 1px; background: var(--border-soft);
}
.acct__cell {
  display: flex; flex-direction: column; gap: 3px;
  padding: 14px 16px; background: var(--bg-panel);
}
.acct__k { font-size: var(--fs-xs); color: var(--text-sub); letter-spacing: .3px; }
.acct__v {
  font-size: 22px; line-height: 1.25; color: var(--text);
  font-variant-numeric: tabular-nums; font-weight: 600;
}
.acct__v.up { color: var(--up); }
.acct__v.down { color: var(--down); }
.acct__sub { font-size: var(--fs-xs); color: var(--text-sub); font-variant-numeric: tabular-nums; }
.acct__sub.up { color: var(--up); }
.acct__sub.down { color: var(--down); }
.acct__sub--ghost { color: transparent; user-select: none; }

.acct__empty {
  display: flex; align-items: center; gap: 7px;
  padding: 18px 16px; font-size: var(--fs-sm); color: var(--text-sub);
}

/* 自校验失败：必须显眼 */
.acct__warn {
  display: flex; align-items: flex-start; gap: 7px;
  padding: 10px 16px;
  background: color-mix(in srgb, var(--warn) 12%, transparent);
  border-top: 1px solid color-mix(in srgb, var(--warn) 35%, transparent);
  font-size: var(--fs-sm); color: var(--warn); line-height: 1.6;
}
.acct__warn > svg { flex: none; margin-top: 2px; }
.acct__warn-item { font-variant-numeric: tabular-nums; }

/* 持仓明细 */
.acct__pos { border-top: 1px solid var(--border-soft); }
.acct__tbl { width: 100%; border-collapse: collapse; font-size: var(--fs-sm); }
.acct__tbl th {
  padding: 7px 12px; text-align: left; font-weight: 500;
  color: var(--text-faint); font-size: var(--fs-xs);
  background: var(--bg-overlay); border-bottom: 1px solid var(--border-soft);
  white-space: nowrap;
}
.acct__tbl td { padding: 9px 12px; color: var(--text); border-bottom: 1px solid var(--border-soft); }
.acct__tbl tr:last-child td { border-bottom: 0; }
.acct__tbl .r { text-align: right; font-variant-numeric: tabular-nums; }
.acct__tbl .up { color: var(--up); }
.acct__tbl .down { color: var(--down); }
.acct__pct { color: inherit; opacity: .75; font-size: var(--fs-xs); }

.acct__verify {
  margin: 0; padding: 8px 12px;
  font-size: var(--fs-xs); color: var(--text-sub);
  background: var(--bg-overlay);
  font-variant-numeric: tabular-nums;
}
.acct__verify-note { color: var(--text-faint); }

.acct__ft {
  display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
  padding: 8px 16px; border-top: 1px solid var(--border-soft);
  background: var(--bg-overlay);
  font-size: var(--fs-xs); color: var(--text-faint);
}
.acct__src { display: inline-flex; align-items: center; gap: 5px; }
.acct__stale { color: var(--warn); font-weight: 600; }
.acct__note { color: var(--text-faint); }
.acct__note::before { content: '·'; margin-right: 6px; opacity: .6; }

.spin { animation: m-spin .9s linear infinite; }

/* 窄屏：两列（4 列在手机/窄窗会挤成一行一列很难读） */
@media (max-width: 720px) {
  .acct__grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .acct__v { font-size: 19px; }
}
</style>
