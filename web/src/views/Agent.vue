<script setup lang="ts">
import { onMounted, onBeforeUnmount, nextTick, ref } from 'vue'
import { useRoute } from 'vue-router'
import PageHeader from '@/components/PageHeader.vue'
import Icon from '@/components/Icon.vue'
import { useToastStore } from '@/stores/toast'
import { agentStream, getAgentHealth, type AgentStreamEvent } from '@/api'

const toast = useToastStore()
const route = useRoute()

interface ToolCall {
  id: string; name: string; args: Record<string, unknown>
  status: 'calling' | 'done' | 'error'; summary?: string; hint?: string
}
interface Msg {
  role: 'user' | 'assistant'
  content: string
  toolCalls?: ToolCall[]
  error?: string
}

const messages = ref<Msg[]>([])
const input = ref('')
const busy = ref(false)
const health = ref<{ llm_configured: boolean; model: string; tools: number } | null>(null)
const scrollEl = ref<HTMLElement | null>(null)
let abort: AbortController | null = null
const streamed: string[] = []
const STORE_KEY = 'sc_agent_messages'

function loadHistory(): Msg[] {
  try {
    const raw = localStorage.getItem(STORE_KEY)
    if (!raw) return []
    const arr = JSON.parse(raw) as Msg[]
    return Array.isArray(arr) ? arr.slice(-50) : []
  } catch { return [] }
}
function saveHistory() {
  try {
    localStorage.setItem(STORE_KEY, JSON.stringify(messages.value.slice(-50)))
  } catch { /* ignore quota */ }
}
messages.value = loadHistory()
if (messages.value.some((m) => m.role === 'assistant' && !m.content && !m.toolCalls?.length)) {
  messages.value = messages.value.filter((m) => !(m.role === 'assistant' && !m.content && !m.toolCalls?.length))
}

onMounted(async () => {
  try { health.value = await getAgentHealth() } catch { health.value = null }
  const prompt = route.query.prompt as string | undefined
  if (prompt) {
    await nextTick()
    send(prompt)
  }
})

onBeforeUnmount(() => abort?.abort())

function clearChat() {
  if (busy.value) return
  messages.value = []
  localStorage.removeItem(STORE_KEY)
}

const QUICK = [
  '看看当前市场环境',
  '列出所有策略',
  '回测 A价值 策略',
  '查看 AI 账户持仓',
  '研究价值因子 BP/EP/ROE',
]

async function scrollBottom() {
  await nextTick()
  scrollEl.value?.scrollTo({ top: scrollEl.value.scrollHeight })
}

function pushUser(text: string) {
  messages.value.push({ role: 'user', content: text })
}

async function send(text?: string) {
  const q = (text ?? input.value).trim()
  if (!q || busy.value) return
  input.value = ''
  busy.value = true
  pushUser(q)
  saveHistory()
  // 组装历史(去掉工具明细, 只留 user/assistant 正文)
  const history: { role: string; content: string }[] = messages.value
    .filter((m) => m.role === 'assistant' || m.role === 'user')
    .map((m) => ({ role: m.role, content: m.content }))

  const msg: Msg = { role: 'assistant', content: '' }
  messages.value.push(msg)
  streamed.length = 0
  const toolMap = new Map<string, ToolCall>()

  abort = new AbortController()
  try {
    await agentStream(history, (ev: AgentStreamEvent) => {
      if (ev.type === 'tool_call') {
        const tc: ToolCall = {
          id: ev.id || (ev.name || 'tool') + streamed.length,
          name: ev.name || 'tool',
          args: ev.args || {},
          status: 'calling',
        }
        toolMap.set(tc.id, tc)
        if (!msg.toolCalls) msg.toolCalls = []
        msg.toolCalls.push(tc)
        scrollBottom()
      } else if (ev.type === 'tool_progress') {
        const tc = toolMap.get(ev.id || '')
        if (tc) tc.hint = ev.message || ''
      } else if (ev.type === 'tool_result') {
        const tc = toolMap.get(ev.id || '')
        if (tc) {
          tc.status = ev.ok ? 'done' : 'error'
          tc.summary = ev.summary || ''
        }
        scrollBottom()
      } else if (ev.type === 'text') {
        streamed.push(ev.delta || '')
        msg.content = streamed.join('')
        scrollBottom()
      } else if (ev.type === 'error') {
        msg.error = ev.message || '未知错误'
      }
    }, abort.signal)
    if (!msg.content) msg.content = '（无文本输出，可以继续提问）'
  } catch (e) {
    if ((e as Error).name === 'AbortError') {
      msg.content = msg.content || '（已停止）'
    } else {
      msg.error = e instanceof Error ? e.message : String(e)
      toast.error('Agent 会话失败：' + msg.error)
    }
  } finally {
    busy.value = false
    abort = null
    saveHistory()
  }
  scrollBottom()
}

function stop() {
  abort?.abort()
}

function fmtArgs(a: Record<string, unknown>): string {
  const e = Object.entries(a)
  if (!e.length) return ''
  return e.map(([k, v]) => `${k}=${typeof v === 'object' ? JSON.stringify(v) : v}`).join(' ')
}

function toolIcon(name: string): string {
  if (/order|cancel/.test(name)) return 'trade'
  if (/position|account|summary/.test(name)) return 'wallet'
  if (/research|factor|backtest|paper|snapshot/.test(name)) return 'research'
  if (/strategy/.test(name)) return 'picks'
  if (/stock|price|search/.test(name)) return 'search'
  if (/regime/.test(name)) return 'market'
  return 'dot'
}

function mk(msg: string): string {
  return msg
    .replace(/```([\s\S]*?)```/g, (_, code: string) => `<pre>${escapeHtml(code)}</pre>`)
    .replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\n/g, '<br/>')
}
function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}
</script>

<template>
  <div class="agent">
    <PageHeader title="AI 操盘台" subtitle="自由调用软件工具：查行情 · 写策略 · 回测 · 盯账户 · 下单">
      <template #right>
        <span v-if="health" :class="['live-badge', health.llm_configured ? 'ok' : 'off']">
          <span class="dot" />{{ health.llm_configured ? `${health.model} 已连接` : '未配置 LLM' }}
        </span>
        <span class="muted tools-count">{{ health?.tools ?? 0 }} 个工具</span>
        <button v-if="messages.length" class="clear-btn" @click="clearChat" title="清空对话">
          <Icon name="trash" :size="14" />
        </button>
      </template>
    </PageHeader>

    <div class="console card">
      <div ref="scrollEl" class="stream">
        <div v-if="!messages.length" class="welcome">
          <Icon name="agentops" :size="36" class="wm-icon" />
          <h3>我是你的 AI 操盘手</h3>
          <p class="muted">可以直接调用软件工具：查行情、搜股票、看账户、下单交易、因子研究、策略回测（写策略→回测→按结果调策略）</p>
          <div class="chips">
            <button v-for="q in QUICK" :key="q" class="chip" @click="send(q)">{{ q }}</button>
          </div>
        </div>

        <template v-for="(m, mi) in messages" :key="mi">
          <div :class="['msg', m.role]">
            <div class="avatar"><Icon :name="m.role === 'user' ? 'settings' : 'agentops'" :size="16" /></div>
            <div class="bubble">
              <template v-if="m.role === 'assistant'">
                <div class="text" v-if="m.content" v-html="mk(m.content)" />
                <div class="text muted" v-else-if="busy && mi === messages.length - 1">思考中…</div>
                <div v-if="m.error" class="err">{{ m.error }}</div>
                <div v-if="m.toolCalls?.length" class="tools">
                  <div v-for="tc in m.toolCalls" :key="tc.id" :class="['tool', tc.status]">
                    <Icon :name="toolIcon(tc.name)" :size="14" />
                    <span class="tname">{{ tc.name }}</span>
                    <span class="targs muted" v-if="fmtArgs(tc.args)">{{ fmtArgs(tc.args) }}</span>
                    <span class="tstate" :class="tc.status">
                      <span v-if="tc.status === 'calling'" class="spin small">⟳</span>
                      <Icon v-else-if="tc.status === 'done'" name="check" :size="13" />
                      <Icon v-else name="alert" :size="13" />
                    </span>
                    <span v-if="tc.hint" class="thint muted">{{ tc.hint }}</span>
                    <span v-if="tc.summary && tc.status !== 'calling'" class="tsum">{{ tc.summary }}</span>
                  </div>
                </div>
              </template>
              <template v-else>
                <div class="text">{{ m.content }}</div>
              </template>
            </div>
          </div>
        </template>
      </div>

      <div class="composer">
        <input
          v-model="input"
          class="inp"
          placeholder="让 AI 做点什么… 例如：写一个 RSI 择时策略并回测"
          :disabled="busy"
          @keydown.enter.prevent="send()"
        />
        <button v-if="busy" class="btn stop" @click="stop">
          <Icon name="stop" :size="15" />
          停止
        </button>
        <button v-else class="btn" :disabled="!input.trim()" @click="send()">
          <Icon name="chat" :size="15" />
          发送
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.agent { max-width: 860px; }
.card {
  background: var(--bg-panel);
  border: 1px solid var(--border-soft);
  border-radius: var(--radius-lg);
  overflow: hidden;
}
.stream { height: calc(100vh - 250px); min-height: 320px; overflow-y: auto; padding: var(--sp-5); display: flex; flex-direction: column; }
.welcome { margin: auto; text-align: center; max-width: 520px; }
.wm-icon { color: var(--gold); margin-bottom: var(--sp-3); }
.welcome h3 { margin: 0 0 var(--sp-2); }
.welcome p { font-size: var(--fs-sm); line-height: 1.6; }
.chips { display: flex; flex-wrap: wrap; gap: var(--sp-2); justify-content: center; margin-top: var(--sp-4); }
.chip {
  padding: 6px 12px; border-radius: var(--radius-pill); border: 1px solid var(--border);
  background: var(--bg-raised); color: var(--text-sub); font-size: var(--fs-xs); cursor: pointer;
}
.chip:hover { border-color: var(--gold); color: var(--gold); }
.msg { display: flex; gap: var(--sp-3); margin-bottom: var(--sp-4); }
.msg.user { flex-direction: row-reverse; }
.avatar {
  width: 30px; height: 30px; border-radius: 50%; flex: none;
  display: flex; align-items: center; justify-content: center;
  background: var(--bg-raised); border: 1px solid var(--border); color: var(--gold);
}
.msg.user .avatar { color: var(--accent); }
.bubble { max-width: 82%; }
.msg.user .bubble { text-align: right; }
.text { font-size: var(--fs-sm); line-height: 1.7; color: var(--text); }
.text pre {
  background: var(--bg); border: 1px solid var(--border); border-radius: var(--radius-sm);
  padding: var(--sp-3); overflow-x: auto; font-size: 11px; font-family: var(--font-mono); margin: var(--sp-2) 0;
}
.text code { background: var(--bg-raised); padding: 1px 5px; border-radius: 4px; font-family: var(--font-mono); font-size: 11px; }
.err { color: var(--up); font-size: var(--fs-sm); margin-top: var(--sp-2); }
.tools { margin-top: var(--sp-3); display: flex; flex-direction: column; gap: var(--sp-2); }
.tool {
  display: flex; align-items: center; gap: var(--sp-2); flex-wrap: wrap;
  background: var(--bg); border: 1px solid var(--border); border-radius: var(--radius-sm);
  padding: 7px 10px; font-size: var(--fs-xs);
}
.tool.error { border-color: var(--up); }
.tool.done { border-color: var(--border-strong); }
.tname { font-family: var(--font-mono); font-weight: 600; color: var(--text); }
.targs { max-width: 340px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tstate { display: inline-flex; align-items: center; }
.tstate.done { color: var(--down); }
.tstate.error { color: var(--up); }
.tstate.calling { color: var(--gold); }
.thint { color: var(--text-faint); }
.tsum { color: var(--text-sub); max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.composer {
  display: flex; gap: var(--sp-2); padding: var(--sp-4);
  border-top: 1px solid var(--border-soft); background: var(--bg-panel);
}
.inp {
  flex: 1; background: var(--bg); border: 1px solid var(--border); border-radius: var(--radius-md);
  padding: 10px 12px; color: var(--text); font-size: var(--fs-sm); outline: none;
}
.inp:focus { border-color: var(--gold); }
.inp:disabled { opacity: 0.6; }
.btn {
  display: inline-flex; align-items: center; gap: var(--sp-2);
  padding: 10px 18px; border: none; border-radius: var(--radius-md);
  background: var(--gold); color: var(--on-gold); font-weight: 700; font-size: var(--fs-sm); cursor: pointer;
}
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.btn.stop { background: var(--up); color: #fff; }
.clear-btn {
  display: inline-flex; align-items: center; justify-content: center;
  width: 30px; height: 30px; border-radius: var(--radius-sm);
  background: transparent; border: 1px solid var(--border); color: var(--text-faint);
  cursor: pointer; transition: color var(--dur-fast);
}
.clear-btn:hover { color: var(--up); border-color: var(--up); }
.live-badge {
  display: inline-flex; align-items: center; gap: var(--sp-1);
  font-size: var(--fs-xs); padding: 3px 10px; border-radius: var(--radius-pill);
  border: 1px solid var(--border);
}
.live-badge.ok { color: var(--down); border-color: var(--down); }
.live-badge.off { color: var(--warn); border-color: var(--warn); }
.live-badge .dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
.tools-count { font-size: var(--fs-xs); }
.muted { color: var(--text-faint); }
.spin.small { display: inline-block; animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
