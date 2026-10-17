<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import PageHeader from '@/components/PageHeader.vue'
import LiveAccount from '@/components/LiveAccount.vue'
import Card from '@/components/Card.vue'
import Icon from '@/components/Icon.vue'
import StatTile from '@/components/ui/StatTile.vue'
import LoadingBlock from '@/components/ui/LoadingBlock.vue'
import EmptyGuide from '@/components/ui/EmptyGuide.vue'
import SegmentedControl from '@/components/ui/SegmentedControl.vue'
import { useToastStore } from '@/stores/toast'
import {
  getLiveStatus, queryLivePanel, queryLiveQuote, liveStartup, liveSnapshot,
  getLiveFills, liveOrderflow, listLiveSnapshots, getLiveIdempotency, liveUnlock,
  type LiveStatus, type LiveRun, type LiveOrderBody,
} from '@/api'

const toast = useToastStore()

/* ───────────── 工具状态 ───────────── */
const st = ref<LiveStatus | null>(null)
const stErr = ref('')
async function loadStatus() {
  stErr.value = ''
  try { st.value = await getLiveStatus() } catch (e: unknown) {
    stErr.value = e instanceof Error ? e.message : '状态读取失败'
  }
}

/* 工具是否"就绪"：能连上客户端。用最近一次调用的结果推断，
   但**不把"最近成功"当作"现在可用"** —— 界面显示的是最近一次探测的时间戳。 */
const lastTs = computed(() => st.value?.last?.ts || '—')
const lastCmd = computed(() => st.value?.last?.command || '—')
const lastOk = computed(() => !!st.value?.last?.ok)

/** 结果严重度：ok / 未就绪（客户端没登录等环境问题）/ 失败 */
const severity = computed<'ok' | 'notready' | 'bad'>(() => {
  const l = st.value?.last
  if (!l) return 'bad'
  if (l.ok) return 'ok'
  const m = l.message || ''
  if (m.includes('未打开') || m.includes('登录') || m.includes('锁定')) return 'notready'
  return 'bad'
})
const severityText = computed(() => (
  severity.value === 'ok' ? '就绪'
    : severity.value === 'notready' ? '客户端未就绪' : '失败'
))

/* ───────────── 会话解锁（券商交易保护超时重锁） ───────────── */

const unlockBusy = ref(false)
const unlockRun = ref<LiveRun | null>(null)

const unlockState = computed(() => st.value?.unlock)
const guard = computed(() => st.value?.login_guard)

/**
 * 是否需要**解锁**（不是"客户端没开"）。
 *
 * ⚠️ 这里收窄过一次判断条件：原来只要消息含「未打开/登录」就弹解锁卡，
 * 但「交易视图未打开（可能需登录）」的真实含义是**客户端根本没开或没登录**，
 * 这时候让人去点"解锁"是错的 —— 客户端没开时解锁必然失败。
 * 所以：只有消息明确含「锁定」，或上次解锁明确失败时，才认为"需要解锁"。
 * 「未打开/需登录」交给工具状态横幅去说明（那是另一回事）。
 */
const looksLocked = computed(() => {
  const m = st.value?.last?.message || ''
  if (m.includes('锁定')) return true
  return unlockState.value?.known === true && unlockState.value.ok === false
})

/** 上次解锁是否失败（失败会让工具自锁，必须显式提示，别让用户反复点） */
const unlockFailed = computed(() => unlockState.value?.known === true && unlockState.value.ok === false)

async function doUnlock() {
  if (guard.value?.guarded) {
    toast.error('工具已自锁（上次密码被判错）。更新凭据文件后才会自动解除，或删除 login-guard.json。')
    return
  }
  if (!confirm(
    '将自动输入交易密码解锁交易界面。\n\n'
    + '• 密码只从凭据文件读取，不会经过网页/日志\n'
    + '• 工具最多只尝试 1 次；若密码被判错会写入自锁，之后不再自动重试\n'
    + '• 输入期间请不要操作鼠标键盘（会抢前台焦点）\n\n'
    + '确定现在解锁？',
  )) return

  unlockBusy.value = true
  try {
    const r = await liveUnlock()
    unlockRun.value = r
    reportRun(r, '解锁成功')
    await loadStatus()
  } catch (e: unknown) {
    toast.error('解锁失败：' + (e instanceof Error ? e.message : String(e)))
  } finally { unlockBusy.value = false }
}

/* ───────────── 面板读取 ───────────── */
type PanelKey = 'positions' | 'funds' | 'deals' | 'cancel'
/** 用 `satisfies` 保持字面量类型，同时避免 `as const` 产生 readonly
    数组（SegmentedControl 的 options 是可变的 {value,label,icon?}[]）。 */
const PANELS = [
  { value: 'positions', label: '持仓', icon: 'holdings' },
  { value: 'funds', label: '资金', icon: 'wallet' },
  { value: 'deals', label: '当日成交', icon: 'trade' },
  { value: 'cancel', label: '当日委托', icon: 'log' },
] satisfies { value: PanelKey; label: string; icon: string }[]

const panel = ref<PanelKey>('positions')
const run = ref<LiveRun | null>(null)
const busy = ref(false)
const bgMode = ref(true)

/** 面板文本：工具把 OCR 文本放在 parameters.text（各面板字段名可能不同，都兜一下） */
const panelText = computed(() => {
  const p = run.value?.result?.parameters as Record<string, unknown> | undefined
  if (!p) return ''
  for (const k of ['text', 'ocr_text', 'content', 'raw']) {
    const v = p[k]
    if (typeof v === 'string' && v.trim()) return v
  }
  return ''
})

/** 结构化行（持仓面板会给 rows/positions；没有就退回文本） */
const panelRows = computed<Record<string, unknown>[]>(() => {
  const p = run.value?.result?.parameters as Record<string, unknown> | undefined
  if (!p) return []
  for (const k of ['positions', 'rows', 'items', 'records']) {
    const v = p[k]
    if (Array.isArray(v)) return v as Record<string, unknown>[]
  }
  return []
})

async function readPanel() {
  busy.value = true
  run.value = null
  try {
    run.value = await queryLivePanel(panel.value, bgMode.value)
    reportRun(run.value)
  } catch (e: unknown) {
    toast.error('读取失败：' + (e instanceof Error ? e.message : String(e)))
  } finally { busy.value = false }
}

/** 统一的成功/失败播报。失败时把工具原话带出来，不要吞掉。 */
function reportRun(r: LiveRun | null, okMsg?: string) {
  if (!r) return
  if (r.error) { toast.error(r.error); return }
  const msg = r.result?.message || ''
  if (r.ok) toast.success(okMsg || msg || '完成')
  else toast.error(msg || `工具返回 exit=${r.exit_code}`)
}

/* ───────────── 实时行情 ───────────── */
const quoteCodes = ref('002659')
const quotes = ref<Record<string, unknown>[]>([])
const quoteBusy = ref(false)
async function doQuote() {
  const codes = quoteCodes.value.split(/[,\s]+/).filter(Boolean)
  if (!codes.length) { toast.error('请输入至少一个 6 位代码'); return }
  quoteBusy.value = true
  try {
    const r = await queryLiveQuote(codes, bgMode.value)
    const p = r.result?.parameters as Record<string, unknown> | undefined
    quotes.value = (p?.quotes as Record<string, unknown>[]) || []
    reportRun(r, `行情已更新（${quotes.value.length} 只）`)
  } catch (e: unknown) {
    toast.error('行情读取失败：' + (e instanceof Error ? e.message : String(e)))
  } finally { quoteBusy.value = false }
}

/* ───────────── 启动 / 快照 ───────────── */
const acting = ref(false)
async function doStartup() {
  acting.value = true
  try {
    const r = await liveStartup()
    reportRun(r, '客户端已就绪')
    await loadStatus()
  } catch (e: unknown) { toast.error('启动失败：' + (e instanceof Error ? e.message : String(e))) }
  finally { acting.value = false }
}
async function doSnapshot() {
  acting.value = true
  try {
    const r = await liveSnapshot()
    reportRun(r, '收盘快照已存档')
    await loadStatus()
    await loadFills()
  } catch (e: unknown) { toast.error('快照失败：' + (e instanceof Error ? e.message : String(e))) }
  finally { acting.value = false }
}

/* ───────────── 成交 / 委托 ───────────── */
const fills = ref<Record<string, unknown>[]>([])
async function loadFills() {
  try {
    const r = await getLiveFills()
    fills.value = r.fills || []
  } catch { /* 无成交时静默 */ }
}

/* ───────────── 下单 ───────────── */
/** 三种下单形态分开做，避免挤成一坨：单笔 / 批量换仓 / 撤单 */
type OrdTab = 'single' | 'batch' | 'cancel'
const ordTab = ref<OrdTab>('single')
const ORD_TABS = [
  { value: 'single', label: '单笔', icon: 'trade' },
  { value: 'batch', label: '批量', icon: 'layers' },
  { value: 'cancel', label: '撤单', icon: 'close' },
] satisfies { value: OrdTab; label: string; icon: string }[]

const order = reactive({
  action: 'buy' as 'buy' | 'sell',
  code: '',
  price: '市价参考' as string,
  qty: 'max' as string,
  allowSt: false,
})
/** 批量：每行一只「代码 价格 数量」，价格/数量可省略（默认 市价参考 / max） */
const batchRows = ref('')
const batchAction = ref<'buy' | 'sell'>('sell')
/** 撤单范围 */
const cancelScope = ref<'all-buy' | 'all-sell'>('all-buy')

/** 下单结果单独存，避免被面板读取覆盖 */
const orderRun = ref<LiveRun | null>(null)
const orderBusy = ref(false)
/** 真下单需二次确认：先点"预演"，看过结果再解锁"真下单" */
const armed = ref(false)

function validCode(c: string) { return /^\d{6}$/.test(c.trim()) }

/** 把文本框解析成工具要的 `代码:价格:数量;...`，同时给出逐行错误 */
const parsedBatch = computed(() => {
  const legs: string[] = []
  const errors: string[] = []
  batchRows.value.split('\n').forEach((raw, i) => {
    const line = raw.trim()
    if (!line || line.startsWith('#')) return
    const parts = line.split(/[\s,，]+/).filter(Boolean)
    const [c, p = '市价参考', q = 'max'] = parts
    if (!validCode(c)) { errors.push(`第 ${i + 1} 行代码非法：${c || '（空）'}`); return }
    if (!/^(\d{1,7}(\.\d{1,3})?|市价参考|auto)$/.test(p)) { errors.push(`第 ${i + 1} 行价格非法：${p}`); return }
    if (!/^(\d{1,9}|all|max)$/.test(q)) { errors.push(`第 ${i + 1} 行数量非法：${q}`); return }
    legs.push(`${c}:${p}:${q}`)
  })
  return { legs, errors }
})

const batchOk = computed(() => parsedBatch.value.legs.length > 0 && parsedBatch.value.errors.length === 0)

async function submitOrder(submit: boolean) {
  let body: LiveOrderBody
  if (ordTab.value === 'single') {
    const code = order.code.trim()
    if (!validCode(code)) { toast.error('股票代码需为 6 位数字'); return }
    body = {
      mode: order.action, code, price: order.price, qty: order.qty,
      submit, yes: submit, allow_st: order.allowSt,
    }
  } else if (ordTab.value === 'batch') {
    if (!batchOk.value) { toast.error('批量列表有误，请先按提示修正'); return }
    body = {
      mode: batchAction.value === 'buy' ? 'buy-multi' : 'sell-multi',
      legs: parsedBatch.value.legs.join(';'),
      submit, yes: submit, allow_st: order.allowSt,
    }
  } else {
    body = { mode: 'cancel', cancel_scope: cancelScope.value, submit, yes: submit }
  }

  if (submit && !armed.value) { toast.error('请先「预演」确认无误，再真下单'); return }

  orderBusy.value = true
  try {
    const r = await liveOrderflow(body)
    orderRun.value = r
    const n = ordTab.value === 'batch' ? parsedBatch.value.legs.length : 1
    reportRun(r, submit
      ? `已提交${ordTab.value === 'batch' ? `（${n} 笔）` : ''}，请核对当日委托`
      : '预演完成（未提交）')
    if (submit) { armed.value = false; await loadFills() }
  } catch (e: unknown) {
    toast.error('下单失败：' + (e instanceof Error ? e.message : String(e)))
  } finally { orderBusy.value = false }
}

/** 任何关键输入变化都要撤销"已解锁"，避免改完参数直接下单 */
function disarm() { armed.value = false }

/** 切 tab 也要撤销解锁 —— 否则"预演了单笔"会给"批量提交"解锁 */
watch(ordTab, disarm)

/* ───────────── 快照列表 ───────────── */
const snaps = ref<string[]>([])
async function loadSnaps() {
  try { snaps.value = (await listLiveSnapshots(8)).snapshots || [] } catch { /* ignore */ }
}

/** 已提交委托（幂等锁记录）—— 对账"我到底提交过几笔、结果如何" */
const idemEntries = ref<Record<string, unknown>[]>([])
const idemCount = computed(() => idemEntries.value.length)
/** 需要人工核查的笔数（工具自己标了 unverified 的） */
const idemUnverified = computed(() => idemEntries.value.filter((e) => e.Status === 'unverified').length)
async function loadIdem() {
  const r = await getLiveIdempotency().catch(() => null)
  idemEntries.value = (r?.entries || []).slice().reverse()
}

onMounted(async () => {
  await Promise.all([loadStatus(), loadFills(), loadSnaps(), loadIdem()])
})
</script>

<template>
  <div class="live">
    <PageHeader title="实盘" subtitle="国信金太阳 · 盘前启动 / 账户读取 / 下单 / 收盘快照">
      <template #right>
        <div class="hdr">
          <button v-if="looksLocked" class="ui-btn unlock-btn" :disabled="unlockBusy || guard?.guarded" @click="doUnlock">
            <Icon name="alert" :size="14" /> {{ unlockBusy ? '解锁中…' : '解锁交易界面' }}
          </button>
          <button class="ui-btn" :disabled="acting" @click="doStartup">
            <Icon name="play" :size="14" /> {{ acting ? '执行中…' : '一键启动/登录' }}
          </button>
          <button class="ui-btn" :disabled="acting" @click="doSnapshot">
            <Icon name="save" :size="14" /> 收盘快照
          </button>
          <button class="ui-btn" @click="loadStatus"><Icon name="refresh" :size="14" /> 刷新状态</button>
        </div>
      </template>
    </PageHeader>

    <!-- ⓪ 账户总览：**置顶**，打开就有数（不必先点"读取"）。
         数据来自策略侧 AUTO_LOG 的人工核对记录 + 最新快照，并如实标注时间与来源。 -->
    <LiveAccount />

    <!-- ⓪ 解锁提示：只在"看起来被锁"时出现，且放在最前面（这是拦路的那一步） -->
    <Card v-if="looksLocked || unlockRun || guard?.guarded" class="sec unlock-card">
      <div class="sec-head">
        <div>
          <h2 class="sec-title">
            <Icon name="alert" :size="15" /> 交易界面需要解锁
          </h2>
          <p class="sec-sub">
            券商的「交易保护」在长时间未操作后会把交易界面锁上。注意：<b>这个界面和首次登录不一样</b> ——
            首次登录是弹窗（账号+密码），超时重锁是<b>嵌在主窗口里的对话框</b>，只有一个交易密码框。
          </p>
        </div>
        <button class="ui-btn unlock-btn" :disabled="unlockBusy || !!guard?.guarded" @click="doUnlock">
          <Icon name="play" :size="14" /> {{ unlockBusy ? '解锁中…' : '解锁' }}
        </button>
      </div>

      <p v-if="guard?.guarded" class="err-box">
        <Icon name="alert" :size="13" />
        工具已自锁：{{ guard.reason || '上次交易密码被服务器判错' }}
        —— 请人工确认密码并更新凭据文件（内容变更后自动解除自锁），或删除 login-guard.json
      </p>

      <p v-if="unlockState?.known" class="sec-sub" :class="unlockState.ok ? 'ok-t' : 'bad-t'">
        上次解锁：{{ unlockState.ok ? '成功' : '失败' }}
        <template v-if="unlockState.ts"> · {{ unlockState.ts }}</template>
        <template v-if="unlockState.detail"> · {{ unlockState.detail }}</template>
      </p>
      <p v-else class="sec-sub faint">上次解锁结果：未知（本会话还没尝试过）</p>

      <div v-if="unlockFailed" class="err-box">
        <Icon name="alert" :size="13" />
        解锁失败会让工具<b>写自锁</b>，之后不会自动重试 —— 这是刻意的：
        券商普遍"密码错误 N 次锁账户"，连续自动重试的代价远大于一次没解开。
      </div>

      <pre v-if="unlockRun?.log_tail" class="log mono">{{ unlockRun.log_tail }}</pre>
    </Card>

    <!-- ① 工具与连接状态：先看这个，再决定能不能操作 -->
    <Card class="sec">
      <div class="sec-head">
        <div>
          <h2 class="sec-title">工具状态</h2>
          <p class="sec-sub">
            最近一次调用：<b class="mono">{{ lastCmd }}</b> ·
            <span class="mono">{{ lastTs }}</span>
          </p>
        </div>
        <label class="bg-toggle" title="后台模式用 PostMessage 投递，不抢你的前台焦点">
          <input v-model="bgMode" type="checkbox" />
          <span>后台模式</span>
        </label>
      </div>

      <LoadingBlock v-if="!st && !stErr" :rows="2" />
      <EmptyGuide v-else-if="stErr" icon="alert" title="读取工具状态失败" :desc="stErr">
        <template #action><button class="ui-btn" @click="loadStatus">重试</button></template>
      </EmptyGuide>
      <template v-else-if="st">
        <EmptyGuide
          v-if="!st.available"
          icon="alert"
          title="未找到实盘工具"
          :desc="`没有在期望位置找到 TradeAutomation.App.exe。请确认 trade-automation 已构建，或用环境变量 SC_TRADE_DIR 指定目录。`"
        />
        <template v-else>
          <!-- 状态横幅：消息可能是一整句话（如「交易视图未打开（可能需登录）」），
               不适合塞进 StatTile 的大号数值位 —— 那里会把一句话渲染成巨型文字。 -->
          <div class="banner" :class="`banner--${severity}`">
            <Icon :name="severity === 'ok' ? 'check' : 'alert'" :size="15" />
            <div class="banner__body">
              <b>{{ severityText }}</b>
              <span v-if="st.last?.message" class="banner__msg">{{ st.last.message }}</span>
            </div>
            <span class="banner__code mono">exit={{ st.last?.exit_code ?? '—' }}</span>
          </div>

          <div class="stats">
            <StatTile label="快照数" :value="String(st.snapshots?.length ?? 0)" />
            <StatTile label="今日成交" :value="String(fills.length)" />
            <StatTile
              label="已提交委托"
              :value="String(idemCount)"
              :hint="idemUnverified ? `${idemUnverified} 笔待人工核查` : '全部已复核'"
              :hint-trend="idemUnverified ? 'down' : 'neutral'"
            />
            <StatTile label="工具目录" :value="st.available ? '已找到' : '缺失'" />
          </div>
          <!-- 工具路径属于排查信息，不用常占一行 -->
          <p class="path faint mono" :title="st.tool_dir">工具：{{ st.tool_dir }}</p>
        </template>
      </template>
    </Card>

    <!-- ② 账户读取 + ③ 实时行情：两栏，互不挤 -->
    <div class="grid2">
      <Card class="sec">
        <div class="sec-head">
          <div>
            <h2 class="sec-title">账户读取</h2>
            <p class="sec-sub">读的是券商客户端面板本身（OCR），因此<b>以客户端为准</b></p>
          </div>
          <button class="ui-btn" :disabled="busy" @click="readPanel">
            <Icon name="refresh" :size="14" /> {{ busy ? '读取中…' : '读取' }}
          </button>
        </div>

        <SegmentedControl v-model="panel" :options="PANELS" />

        <p v-if="run && !run.ok" class="err-box">
          <Icon name="alert" :size="13" />
          {{ run.result?.message || run.error || `exit=${run.exit_code}` }}
        </p>

        <LoadingBlock v-if="busy" :rows="3" />
        <template v-else-if="run?.ok">
          <table v-if="panelRows.length" class="tbl">
            <thead>
              <tr><th v-for="k in Object.keys(panelRows[0])" :key="k">{{ k }}</th></tr>
            </thead>
            <tbody>
              <tr v-for="(r, i) in panelRows" :key="i">
                <td v-for="k in Object.keys(panelRows[0])" :key="k" class="num">{{ r[k] }}</td>
              </tr>
            </tbody>
          </table>
          <pre v-else-if="panelText" class="ocr mono">{{ panelText }}</pre>
          <p v-else class="faint">面板已读取，但工具未返回结构化行或文本。</p>
        </template>
        <!-- 空态用一行说明即可：持仓/资金总览已在上方「账户总览」，
             这里只剩"读成交/委托明细"一个用途，不值得占一大块引导区 -->
        <p v-else class="faint hint-line">
          未读取。客户端已登录时点「读取」可取成交 / 委托明细（持仓与资金已在上方总览）。
        </p>
      </Card>

      <Card class="sec">
        <div class="sec-head">
          <div>
            <h2 class="sec-title">实时行情</h2>
            <p class="sec-sub">现价 / 涨停 / 昨收 / 跌停，可一次多只（逗号分隔）</p>
          </div>
        </div>
        <div class="q-row">
          <input v-model="quoteCodes" class="ui-input" placeholder="002659,600036" @keyup.enter="doQuote" />
          <button class="ui-btn" :disabled="quoteBusy" @click="doQuote">
            {{ quoteBusy ? '查询中…' : '查询' }}
          </button>
        </div>
        <table v-if="quotes.length" class="tbl">
          <thead>
            <tr><th>代码</th><th>名称</th><th>现价</th><th>涨停</th><th>昨收</th><th>跌停</th></tr>
          </thead>
          <tbody>
            <tr v-for="q in quotes" :key="String(q.code)">
              <td class="mono">{{ q.code }}</td>
              <td>{{ q.name }}</td>
              <td class="num">{{ q.price }}</td>
              <td class="num up">{{ q.limit_up }}</td>
              <td class="num">{{ q.prev_close }}</td>
              <td class="num down">{{ q.limit_down }}</td>
            </tr>
          </tbody>
        </table>
        <p v-else class="faint">输入代码后点「查询」。</p>
      </Card>
    </div>

    <!-- ④ 下单：与只读区物理隔开，并强制"预演 → 真下单"两步 -->
    <Card class="sec order-sec">
      <div class="sec-head">
        <div>
          <h2 class="sec-title">下单</h2>
          <p class="sec-sub">
            默认<b>只预演</b>（切面板→填单→校验→截图，不提交）。
            真下单前必须先预演确认，且本页会再问一次。
          </p>
        </div>
      </div>

      <SegmentedControl v-model="ordTab" :options="ORD_TABS" />

      <!-- 单笔 -->
      <div v-if="ordTab === 'single'" class="ord-grid">
        <div class="fld">
          <label>方向</label>
          <SegmentedControl
            :model-value="order.action"
            :options="[{ value: 'buy', label: '买入', icon: 'arrow-up-right' }, { value: 'sell', label: '卖出', icon: 'arrow-down-right' }]"
            @update:model-value="(v: string) => { order.action = v as 'buy' | 'sell'; disarm() }"
          />
        </div>
        <div class="fld">
          <label>代码</label>
          <input v-model="order.code" class="ui-input" placeholder="600000" @input="disarm" />
        </div>
        <div class="fld">
          <label>价格</label>
          <input v-model="order.price" class="ui-input" placeholder="市价参考 或 5.26" @input="disarm" />
        </div>
        <div class="fld">
          <label>数量</label>
          <input v-model="order.qty" class="ui-input" placeholder="max / all / 100" @input="disarm" />
        </div>
      </div>

      <!-- 批量换仓 -->
      <div v-else-if="ordTab === 'batch'" class="batch">
        <div class="batch-head">
          <SegmentedControl
            :model-value="batchAction"
            :options="[{ value: 'sell', label: '批量卖出', icon: 'arrow-down-right' }, { value: 'buy', label: '批量买入', icon: 'arrow-up-right' }]"
            @update:model-value="(v: string) => { batchAction = v as 'buy' | 'sell'; disarm() }"
          />
          <span class="faint">每行一只：<code>代码 价格 数量</code>（价格/数量可省略 → 默认「市价参考 / max」）</span>
        </div>
        <textarea
          v-model="batchRows"
          class="ui-textarea batch-ta mono"
          rows="6"
          spellcheck="false"
          placeholder="600238 市价参考 all&#10;600576 5.26 max"
          @input="disarm"
        />
        <div class="batch-foot">
          <span v-if="parsedBatch.errors.length" class="bad-t">
            <Icon name="alert" :size="12" /> {{ parsedBatch.errors[0] }}
            <template v-if="parsedBatch.errors.length > 1">（共 {{ parsedBatch.errors.length }} 处）</template>
          </span>
          <span v-else-if="parsedBatch.legs.length" class="ok-t">
            <Icon name="check" :size="12" /> 将执行 {{ parsedBatch.legs.length }} 笔
          </span>
          <span v-else class="faint">还没有有效行</span>
        </div>
        <p class="sec-sub">
          ⚠️ 批量是<b>逐笔提交、逐笔复核、失败即停</b>：中途失败时，之前的笔已成交，
          之后的笔不会执行。请用「当日委托 / 当日成交」核对实际结果。
        </p>
      </div>

      <!-- 撤单 -->
      <div v-else class="cancel-box">
        <div class="fld">
          <label>撤销范围</label>
          <SegmentedControl
            :model-value="cancelScope"
            :options="[{ value: 'all-buy', label: '全部买单', icon: 'arrow-down-right' }, { value: 'all-sell', label: '全部卖单', icon: 'arrow-up-right' }]"
            @update:model-value="(v: string) => { cancelScope = v as 'all-buy' | 'all-sell'; disarm() }"
          />
        </div>
        <p class="sec-sub">
          工具会<b>前后列表对比复核</b>，确认目标委托确实消失。撤单本身不改持仓，但会取消未成交的挂单。
        </p>
      </div>

      <label class="chk chk--line" title="ST/*ST/退 默认拒绝买入，勾选后允许">
        <input v-model="order.allowSt" type="checkbox" @change="disarm" />
        <span>允许 ST（默认拒绝买入；卖出不受限）</span>
      </label>

      <div class="ord-actions">
        <button class="ui-btn" :disabled="orderBusy || (ordTab === 'batch' && !batchOk)" @click="submitOrder(false)">
          <Icon name="research" :size="14" /> {{ orderBusy ? '执行中…' : '预演（不提交）' }}
        </button>
        <button v-if="!armed" class="ui-btn" disabled title="请先预演">
          <Icon name="trade" :size="14" /> 真下单（先预演）
        </button>
        <button v-else class="ui-btn danger" :disabled="orderBusy" @click="submitOrder(true)">
          <Icon name="alert" :size="14" /> 确认真下单
        </button>
        <span v-if="armed" class="armed-note">
          已解锁：再点一次将<b>真实提交委托</b>
        </span>
      </div>

      <!-- 预演结果：解锁"真下单"的唯一依据 -->
      <div v-if="orderRun" class="ord-result" :class="orderRun.ok ? 'is-ok' : 'is-bad'">
        <div class="ord-result__head">
          <Icon :name="orderRun.ok ? 'check' : 'alert'" :size="14" />
          <b>{{ orderRun.ok ? (orderRun.submitted ? '已提交' : '预演成功') : '失败' }}</b>
          <span class="faint">exit={{ orderRun.exit_code }} · {{ orderRun.elapsed }}s</span>
        </div>
        <p v-if="orderRun.result?.message" class="mono">{{ orderRun.result.message }}</p>
        <pre v-if="orderRun.log_tail" class="log mono">{{ orderRun.log_tail }}</pre>
        <button v-if="orderRun.ok && !orderRun.submitted" class="ui-btn" @click="armed = true">
          预演无误 → 解锁真下单
        </button>
      </div>
    </Card>

    <!-- ⑤ 成交与快照：属于「事后核对」，默认收起，避免把主操作挤到下面 -->
    <details class="fold">
      <summary>
        <Icon name="log" :size="13" />
        事后核对：今日成交 · 收盘快照
        <span v-if="idemUnverified" class="bad-t">（{{ idemUnverified }} 笔待核查）</span>
      </summary>
      <div class="grid2 fold__body">
        <Card class="sec">
        <h2 class="sec-title">今日成交（对账）</h2>
        <p class="sec-sub">来源 fills_YYYYMMDD.jsonl；空表示当日无成交</p>
        <table v-if="fills.length" class="tbl">
          <thead>
            <tr><th v-for="k in Object.keys(fills[0]).slice(0, 7)" :key="k">{{ k }}</th></tr>
          </thead>
          <tbody>
            <tr v-for="(f, i) in fills" :key="i">
              <td v-for="k in Object.keys(fills[0]).slice(0, 7)" :key="k" class="num">{{ f[k] }}</td>
            </tr>
          </tbody>
        </table>
        <p v-else class="faint">当日无成交记录。</p>

        <!-- 幂等锁：工具替我们记的"提交过什么、复核结果如何"。
             其中 unverified 是工具明确要求人工核查的，必须显式提示。 -->
        <details class="idem" :open="idemUnverified > 0">
          <summary>
            已提交委托记录（{{ idemCount }} 笔
            <template v-if="idemUnverified">，<b class="bad-t">{{ idemUnverified }} 笔待核查</b></template>）
          </summary>
          <ul class="idem-list">
            <li v-for="(e, i) in idemEntries" :key="i" :class="{ 'is-bad': e.Status === 'unverified' }">
              <span class="mono">{{ e.Ts }}</span>
              <span class="idem-key mono">{{ e.Key }}</span>
              <span class="idem-note">{{ e.Note }}</span>
            </li>
          </ul>
        </details>
      </Card>

      <Card class="sec">
        <h2 class="sec-title">收盘快照</h2>
        <p class="sec-sub">snapshots/ 下按时间倒序（点「收盘快照」生成新的一份）</p>
        <ul v-if="snaps.length" class="snap-list">
          <li v-for="s in snaps" :key="s" class="mono">{{ s }}</li>
        </ul>
        <p v-else class="faint">还没有快照。</p>
      </Card>
      </div>
    </details>
  </div>
</template>

<style scoped>
.live { max-width: 1280px; }
.sec { margin-bottom: var(--sp-5); padding: var(--sp-5); }

/* 可折叠区块（事后核对类）：默认收起，展开后内部卡片不再叠底边距 */
.fold { margin-bottom: var(--sp-5); }
.fold > summary {
  display: flex; align-items: center; gap: 7px;
  padding: 10px 14px; cursor: pointer; user-select: none;
  border: 1px solid var(--border-soft); border-radius: var(--radius-md);
  background: var(--bg-panel); color: var(--text-sub); font-size: var(--fs-sm);
}
.fold > summary:hover { color: var(--text); border-color: var(--border-strong); }
.fold__body { margin-top: var(--sp-4); }
.fold__body .sec:last-child { margin-bottom: 0; }
.hint-line { margin: var(--sp-4) 0 0; font-size: var(--fs-sm); line-height: 1.6; }
.sec-head {
  display: flex; align-items: flex-start; justify-content: space-between;
  gap: var(--sp-4); margin-bottom: var(--sp-4);
}
.sec-title { font-size: var(--fs-lg); font-weight: 600; color: var(--text); margin: 0 0 var(--sp-1); }
.sec-sub { margin: 0; font-size: var(--fs-sm); color: var(--text-sub); line-height: 1.55; }
.hdr { display: flex; gap: var(--sp-2); flex-wrap: wrap; }

/* 解锁卡：用警示色，因为它是"拦路"的那一步 */
.unlock-card { border: 1px solid color-mix(in srgb, var(--warn) 50%, var(--border)); }
.unlock-card .sec-title { display: flex; align-items: center; gap: 6px; color: var(--warn); }
.unlock-btn {
  background: var(--warn); border-color: var(--warn); color: #1a1206; font-weight: 600;
}
.unlock-btn:disabled { opacity: 0.5; }

.bg-toggle {
  display: inline-flex; align-items: center; gap: 6px;
  font-size: var(--fs-sm); color: var(--text-sub); cursor: pointer; white-space: nowrap;
}
.stats { display: grid; gap: var(--sp-3); grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); }

/* 状态横幅：把「一句话状态 + 退出码」从 StatTile 的大号数值位里拿出来 */
.banner {
  display: flex; align-items: flex-start; gap: var(--sp-3);
  padding: 10px 14px; margin-bottom: var(--sp-4);
  border-radius: var(--radius-md); border: 1px solid var(--border);
  background: var(--bg-panel);
}
.banner__body { display: flex; flex-direction: column; gap: 2px; min-width: 0; flex: 1; }
.banner__body b { font-size: var(--fs-md); }
.banner__msg { font-size: var(--fs-sm); color: var(--text-sub); word-break: break-word; }
.banner__code { font-size: var(--fs-xs); color: var(--text-faint); white-space: nowrap; }
.banner--ok { border-color: color-mix(in srgb, var(--ok) 45%, var(--border)); color: var(--ok); }
.banner--notready { border-color: color-mix(in srgb, var(--warn) 45%, var(--border)); color: var(--warn); }
.banner--bad { border-color: color-mix(in srgb, var(--up) 45%, var(--border)); color: var(--up); }

.path { margin: var(--sp-3) 0 0; font-size: var(--fs-xs); word-break: break-all; }
.ok-t { color: var(--ok); }
.bad-t { color: var(--warn); }

.grid2 { display: grid; gap: var(--sp-4); grid-template-columns: repeat(auto-fit, minmax(400px, 1fr)); }

.err-box {
  display: flex; align-items: center; gap: 6px; margin: var(--sp-3) 0;
  padding: 8px 12px; border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--warn) 14%, transparent);
  color: var(--warn); font-size: var(--fs-sm);
}
.ocr {
  max-height: 340px; overflow: auto; margin: var(--sp-3) 0 0; padding: var(--sp-3);
  background: var(--bg); border: 1px solid var(--border-soft); border-radius: var(--radius-sm);
  font-size: var(--fs-xs); line-height: 1.6; white-space: pre-wrap;
}

.q-row { display: flex; gap: var(--sp-2); margin-bottom: var(--sp-3); }
.q-row .ui-input { flex: 1; }

/* 下单区：整块用警示色描边，和只读区在视觉上区分开 */
.order-sec { border: 1px solid var(--border-strong); }
.ord-grid {
  display: grid; gap: var(--sp-3); margin-top: var(--sp-3);
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  align-items: end;
}
.fld { display: flex; flex-direction: column; gap: 5px; }
.fld label { font-size: var(--fs-xs); color: var(--text-faint); }
.chk {
  display: inline-flex; align-items: center; gap: 6px;
  font-size: var(--fs-sm); color: var(--text-sub); cursor: pointer;
}
.chk--line { margin-top: var(--sp-4); }

/* 批量换仓 */
.batch { display: flex; flex-direction: column; gap: var(--sp-3); margin-top: var(--sp-3); }
.batch-head { display: flex; align-items: center; gap: var(--sp-3); flex-wrap: wrap; }
.batch-head .faint { font-size: var(--fs-xs); }
.batch-head code {
  padding: 1px 5px; border-radius: 4px;
  background: var(--bg-raised); border: 1px solid var(--border-soft);
}
.batch-ta {
  width: 100%; resize: vertical; line-height: 1.7;
  font-size: var(--fs-sm); padding: 10px 12px;
}
.batch-foot { display: flex; align-items: center; gap: 6px; font-size: var(--fs-xs); }
.batch .sec-sub { margin: 0; }

/* 撤单 */
.cancel-box { margin-top: var(--sp-3); }
.cancel-box .sec-sub { margin-top: var(--sp-3); }
.ord-actions {
  display: flex; align-items: center; gap: var(--sp-3);
  flex-wrap: wrap; margin-top: var(--sp-4);
}
.armed-note { font-size: var(--fs-sm); color: var(--warn); }
.ui-btn.danger {
  background: var(--up); border-color: var(--up); color: #fff;
}

.ord-result {
  margin-top: var(--sp-4); padding: var(--sp-3) var(--sp-4);
  border-radius: var(--radius-md); border: 1px solid var(--border);
  background: var(--bg-panel);
}
.ord-result.is-ok { border-color: color-mix(in srgb, var(--ok) 45%, var(--border)); }
.ord-result.is-bad { border-color: color-mix(in srgb, var(--warn) 45%, var(--border)); }
.ord-result__head { display: flex; align-items: center; gap: var(--sp-2); font-size: var(--fs-sm); }
.ord-result__head .faint { margin-left: auto; }
.ord-result p { margin: var(--sp-2) 0 0; font-size: var(--fs-sm); }
.log {
  max-height: 200px; overflow: auto; margin: var(--sp-3) 0;
  padding: var(--sp-2); background: var(--bg); border-radius: var(--radius-sm);
  font-size: var(--fs-xs); white-space: pre-wrap; line-height: 1.5;
}
.snap-list { margin: 0; padding-left: 1.1em; font-size: var(--fs-sm); line-height: 1.9; color: var(--text-sub); }

/* 幂等锁记录（提交过的委托 + 复核结果） */
.idem { margin-top: var(--sp-4); border-top: 1px solid var(--border-soft); padding-top: var(--sp-3); }
.idem summary {
  cursor: pointer; font-size: var(--fs-sm); color: var(--text-sub);
  padding: 4px 0; user-select: none;
}
.idem summary:hover { color: var(--text); }
.idem-list { margin: var(--sp-2) 0 0; padding: 0; list-style: none; }
.idem-list li {
  display: grid; gap: 2px var(--sp-3); padding: 7px 0;
  border-bottom: 1px solid var(--border-soft);
  grid-template-columns: auto 1fr;
  font-size: var(--fs-xs);
}
.idem-list li:last-child { border-bottom: none; }
.idem-list li.is-bad { color: var(--warn); }
.idem-key { color: var(--text-sub); word-break: break-all; }
.idem-list li.is-bad .idem-key { color: var(--warn); }
.idem-note { grid-column: 2; color: var(--text-faint); line-height: 1.5; }
.idem-list li.is-bad .idem-note { color: color-mix(in srgb, var(--warn) 80%, var(--text-faint)); }
</style>
