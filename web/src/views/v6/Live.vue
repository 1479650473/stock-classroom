<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import PageHeader from '@/components/PageHeader.vue'
import Card from '@/components/Card.vue'
import Icon from '@/components/Icon.vue'
import StatTile from '@/components/ui/StatTile.vue'
import LoadingBlock from '@/components/ui/LoadingBlock.vue'
import EmptyGuide from '@/components/ui/EmptyGuide.vue'
import SegmentedControl from '@/components/ui/SegmentedControl.vue'
import { useToastStore } from '@/stores/toast'
import {
  getLiveStatus, queryLivePanel, queryLiveQuote, liveStartup, liveSnapshot,
  getLiveFills, liveOrderflow, listLiveSnapshots,
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
const order = reactive({
  action: 'buy' as 'buy' | 'sell',
  code: '',
  price: '市价参考' as string,
  qty: 'max' as string,
  allowSt: false,
})
/** 下单结果单独存，避免被面板读取覆盖 */
const orderRun = ref<LiveRun | null>(null)
const orderBusy = ref(false)
/** 真下单需二次确认：先点"预演"，看过结果再解锁"真下单" */
const armed = ref(false)

function validCode(c: string) { return /^\d{6}$/.test(c.trim()) }

async function submitOrder(submit: boolean) {
  const code = order.code.trim()
  if (!validCode(code)) { toast.error('股票代码需为 6 位数字'); return }
  if (submit && !armed.value) { toast.error('请先「预演」确认无误，再真下单'); return }

  const body: LiveOrderBody = {
    mode: order.action,
    code,
    price: order.price,
    qty: order.qty,
    submit,
    yes: submit,             // 真下单才跳过人工确认框（UI 已提供二次确认）
    allow_st: order.allowSt,
  }
  orderBusy.value = true
  try {
    const r = await liveOrderflow(body)
    orderRun.value = r
    reportRun(r, submit ? '已提交（请核对当日委托）' : '预演完成（未提交）')
    if (submit) { armed.value = false; await loadFills() }
  } catch (e: unknown) {
    toast.error('下单失败：' + (e instanceof Error ? e.message : String(e)))
  } finally { orderBusy.value = false }
}

/** 任何关键输入变化都要撤销"已解锁"，避免改完参数直接下单 */
function disarm() { armed.value = false }

/* ───────────── 快照列表 ───────────── */
const snaps = ref<string[]>([])
async function loadSnaps() {
  try { snaps.value = (await listLiveSnapshots(8)).snapshots || [] } catch { /* ignore */ }
}

onMounted(async () => {
  await Promise.all([loadStatus(), loadFills(), loadSnaps()])
})
</script>

<template>
  <div class="live">
    <PageHeader title="实盘" subtitle="国信金太阳 · 盘前启动 / 账户读取 / 下单 / 收盘快照">
      <template #right>
        <div class="hdr">
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

    <!-- ① 工具与连接状态：先看这个，再决定能不能操作 -->
    <Card class="sec">
      <div class="sec-head">
        <div>
          <h2 class="sec-title">工具状态</h2>
          <p class="sec-sub">
            最近一次调用：<b class="mono">{{ lastCmd }}</b> ·
            <span class="mono">{{ lastTs }}</span> ·
            <span :class="lastOk ? 'ok-t' : 'bad-t'">{{ lastOk ? '成功' : '失败/未知' }}</span>
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
          <div class="stats">
            <StatTile label="最近消息" :value="st.last?.message || '—'" />
            <StatTile label="退出码" :value="String(st.last?.exit_code ?? '—')" />
            <StatTile label="快照数" :value="String(st.snapshots?.length ?? 0)" />
            <StatTile label="今日成交" :value="String(fills.length)" />
          </div>
          <p class="path faint mono">{{ st.tool_dir }}</p>
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
        <EmptyGuide
          v-else
          icon="holdings"
          title="还没有读取"
          desc="点「读取」获取持仓 / 资金 / 当日成交 / 当日委托。需要客户端已登录；未登录时工具会明确报错，不会返回误导性的空结果。"
        />
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

      <div class="ord-grid">
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
        <label class="chk" title="ST/*ST/退 默认拒绝买入，勾选后允许">
          <input v-model="order.allowSt" type="checkbox" @change="disarm" />
          <span>允许 ST（默认拒绝）</span>
        </label>
      </div>

      <div class="ord-actions">
        <button class="ui-btn" :disabled="orderBusy" @click="submitOrder(false)">
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

    <!-- ⑤ 成交与快照 -->
    <div class="grid2">
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
  </div>
</template>

<style scoped>
.live { max-width: 1280px; }
.sec { margin-bottom: var(--sp-5); padding: var(--sp-5); }
.sec-head {
  display: flex; align-items: flex-start; justify-content: space-between;
  gap: var(--sp-4); margin-bottom: var(--sp-4);
}
.sec-title { font-size: var(--fs-lg); font-weight: 600; color: var(--text); margin: 0 0 var(--sp-1); }
.sec-sub { margin: 0; font-size: var(--fs-sm); color: var(--text-sub); line-height: 1.55; }
.hdr { display: flex; gap: var(--sp-2); flex-wrap: wrap; }

.bg-toggle {
  display: inline-flex; align-items: center; gap: 6px;
  font-size: var(--fs-sm); color: var(--text-sub); cursor: pointer; white-space: nowrap;
}
.stats { display: grid; gap: var(--sp-3); grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); }
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
  display: grid; gap: var(--sp-3);
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  align-items: end;
}
.fld { display: flex; flex-direction: column; gap: 5px; }
.fld label { font-size: var(--fs-xs); color: var(--text-faint); }
.chk {
  display: inline-flex; align-items: center; gap: 6px;
  font-size: var(--fs-sm); color: var(--text-sub); cursor: pointer;
}
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
</style>
