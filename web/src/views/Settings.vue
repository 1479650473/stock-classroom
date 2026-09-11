<script setup lang="ts">
import { ref, computed, reactive, onMounted } from 'vue'
import PageHeader from '@/components/PageHeader.vue'
import Card from '@/components/Card.vue'
import Icon from '@/components/Icon.vue'
import { useAppStore } from '@/stores/app'
import { useToastStore } from '@/stores/toast'
import { getSettings, saveSettings, testLlm, getScheduler, saveScheduler, schedulerRunNow } from '@/api'

const app = useAppStore()
const toast = useToastStore()

// ─── AI 定时 ───
const sch = reactive({ enabled: false, at: '17:00', hp: 20, log: '' })
const schSaving = ref(false)
const schRunning = ref(false)
const schStatus = ref('')

async function loadScheduler() {
  try {
    const s = await getScheduler()
    sch.enabled = !!s.enabled
    sch.at = s.at || '17:00'
    sch.hp = s.hp || 20
    sch.log = s.log || ''
    schStatus.value = s.last_finish ? `完成于 ${s.last_finish.replace(/T/g, ' ').slice(0, 19)}` : '（从未运行）'
  } catch { /* ignore */ }
}
async function saveSchedulerCfg() {
  schSaving.value = true
  try {
    const s = await saveScheduler({ enabled: sch.enabled, at: sch.at, hp: sch.hp })
    toast.success(s.enabled ? `定时已启用（每天 ${s.at}）` : '定时已关闭')
  } catch (e: unknown) {
    toast.error('保存失败：' + (e instanceof Error ? e.message : String(e)))
  } finally { schSaving.value = false }
}
async function runNow() {
  schRunning.value = true
  try {
    const r = await schedulerRunNow()
    if (r.queued) toast.info('任务已排队，可在指挥舱/日志查看进度')
    else toast.info(r.reason || '今日已跑过')
    await loadScheduler()
  } catch (e: unknown) {
    toast.error('触发失败：' + (e instanceof Error ? e.message : String(e)))
  } finally { schRunning.value = false }
}

const themeOptions = [
  { key: 'graphite' as const, label: '石墨', color: '#D4A574' },
  { key: 'obsidian' as const, label: '黑曜', color: '#E0A050' },
  { key: 'ivory' as const, label: '象牙', color: '#8E3A2F' },
]
const fontSizeOptions = [12, 13, 14, 15, 16]

const agentBase = ref('')
const agentKey = ref('')
const agentModel = ref('')
const testingLlm = ref(false)
const saving = ref(false)

onMounted(async () => {
  try {
    const s = await getSettings()
    const agent = (s.agent as Record<string, unknown>) || {}
    agentBase.value = (agent.api_base as string) || ''
    agentKey.value = (agent.api_key as string) || ''
    agentModel.value = (agent.model as string) || ''
    if (s.theme) app.setTheme((s.theme as string) as 'graphite' | 'obsidian' | 'ivory')
    if (s.font_size) app.setFontSize(Number(s.font_size))
  } catch { /* 未配置时静默 */ }
  loadScheduler()
})

const isMaskedKey = computed(() => agentKey.value.startsWith('****'))

async function testConnection() {
  if (!agentBase.value || !agentKey.value) { toast.error('请填写 API Base 和 API Key'); return }
  testingLlm.value = true
  try {
    await testLlm({ api_base: agentBase.value, api_key: agentKey.value, model: agentModel.value })
    toast.success('LLM 连接正常')
  } catch (e: unknown) {
    toast.error('LLM 连接失败：' + (e instanceof Error ? e.message : String(e)))
  } finally { testingLlm.value = false }
}

async function save() {
  saving.value = true
  try {
    await saveSettings({
      theme: app.theme,
      font_size: app.fontSize,
      agent: {
        api_base: agentBase.value,
        api_key: isMaskedKey.value ? null : agentKey.value,
        model: agentModel.value,
      },
    })
    toast.success('设置已保存')
  } catch (e: unknown) {
    toast.error('保存失败：' + (e instanceof Error ? e.message : String(e)))
  } finally { saving.value = false }
}
</script>

<template>
  <div class="settings">
    <PageHeader title="设置" subtitle="外观与系统配置">
      <template #right>
        <button class="btn" @click="save" :disabled="saving">
          <Icon v-if="saving" name="refresh" :size="14" class="spin" />
          {{ saving ? '保存中…' : '保存设置' }}
        </button>
      </template>
    </PageHeader>

    <Card class="sec">
      <h2 class="sec-title">外观</h2>
      <div class="row">
        <label class="lbl">主题</label>
        <div class="opts">
          <button
            v-for="t in themeOptions"
            :key="t.key"
            class="theme-btn"
            :class="{ active: app.theme === t.key }"
            @click="app.setTheme(t.key)"
          >
            <span class="swatch" :style="{ background: t.color }" />
            {{ t.label }}
          </button>
        </div>
      </div>
      <div class="row">
        <label class="lbl">字体大小</label>
        <div class="opts">
          <button
            v-for="f in fontSizeOptions"
            :key="f"
            class="num-btn"
            :class="{ active: app.fontSize === f }"
            @click="app.setFontSize(f)"
          >
            {{ f }}px
          </button>
        </div>
      </div>
    </Card>

    <Card class="sec">
      <h2 class="sec-title">AI 模型</h2>
      <div class="field">
        <label class="lbl">API Base URL</label>
        <input v-model="agentBase" class="inp" placeholder="https://api.deepseek.com" />
      </div>
      <div class="field">
        <label class="lbl">API Key {{ isMaskedKey ? '(已保存，留空保持)' : '' }}</label>
        <input v-model="agentKey" class="inp" type="password" placeholder="sk-..." />
      </div>
      <div class="field">
        <label class="lbl">模型</label>
        <input v-model="agentModel" class="inp" placeholder="deepseek-flash" />
      </div>
      <div class="actions">
        <button class="btn ghost" @click="testConnection" :disabled="testingLlm">
          <Icon v-if="testingLlm" name="refresh" :size="14" class="spin" />
          {{ testingLlm ? '测试中…' : '测试连接' }}
        </button>
      </div>
    </Card>

    <Card class="sec">
      <h2 class="sec-title">AI 定时自主交易</h2>
      <div class="row">
        <label class="lbl">启用</label>
        <button :class="['toggle', { on: sch.enabled }]" @click="sch.enabled = !sch.enabled">
          <span class="knob" />
        </button>
        <span class="muted-note">每日收盘后自动：数据更新 → 策略进化 → 持仓守护真卖 → 记账</span>
      </div>
      <div class="row">
        <label class="lbl">执行时间</label>
        <input v-model="sch.at" class="inp time-inp" type="time" />
        <label class="lbl">持有期</label>
        <select v-model="sch.hp" class="inp sel-inp">
          <option :value="10">10 bar</option>
          <option :value="20">20 bar</option>
          <option :value="40">40 bar</option>
        </select>
      </div>
      <div class="row">
        <div class="actions">
          <button class="btn ghost" @click="saveSchedulerCfg" :disabled="schSaving">
            <Icon v-if="schSaving" name="refresh" :size="14" class="spin" />
            保存定时
          </button>
          <button class="btn" @click="runNow" :disabled="schRunning">
            <Icon :name="schRunning ? 'refresh' : 'play'" :size="14" :class="{ spin: schRunning }" />
            {{ schRunning ? '跑一次中…' : '立即跑一次' }}
          </button>
        </div>
      </div>
      <div v-if="schStatus" class="field">
        <label class="lbl">上次运行</label>
        <div class="muted-note num">{{ schStatus }}</div>
      </div>
      <div v-if="sch.log" class="field">
        <label class="lbl">运行日志</label>
        <pre class="log">{{ sch.log }}</pre>
      </div>
    </Card>
  </div>
</template>

<style scoped>
.settings { max-width: 640px; }
.sec {
  margin-bottom: var(--sp-5);
  padding: var(--sp-5);
}
.sec-title { font-size: var(--fs-lg); font-weight: 600; color: var(--text); margin: 0 0 var(--sp-4); }
.row { display: flex; align-items: center; gap: var(--sp-4); margin-bottom: var(--sp-3); }
.lbl { font-size: var(--fs-sm); color: var(--text-sub); min-width: 80px; }
.opts { display: flex; gap: var(--sp-2); }
.theme-btn, .num-btn {
  display: inline-flex; align-items: center; gap: var(--sp-2);
  padding: 7px 14px; border: 1px solid var(--border); border-radius: var(--radius-sm);
  background: transparent; color: var(--text-sub); font-size: var(--fs-sm); cursor: pointer;
  transition: border-color var(--dur-fast), color var(--dur-fast);
}
.theme-btn.active, .num-btn.active { border-color: var(--gold); color: var(--gold); }
.swatch { width: 12px; height: 12px; border-radius: 50%; border: 1px solid var(--border-soft); }
.field { margin-bottom: var(--sp-3); display: flex; flex-direction: column; gap: var(--sp-1); }
.inp {
  background: var(--bg); border: 1px solid var(--border); border-radius: var(--radius-sm);
  padding: 8px 12px; color: var(--text); font-size: var(--fs-md); width: 100%;
}
.inp:focus { border-color: var(--gold); outline: none; }
.actions { margin-top: var(--sp-2); }
.btn {
  display: inline-flex; align-items: center; gap: var(--sp-2);
  padding: 9px 18px; background: var(--gold); color: var(--bg);
  border: none; border-radius: var(--radius-sm); font-weight: 600; cursor: pointer;
  transition: opacity var(--dur-fast);
}
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.btn.ghost { background: var(--bg-raised); color: var(--text-sub); border: 1px solid var(--border); }
.toggle {
  position: relative; width: 42px; height: 22px; border-radius: var(--radius-pill);
  background: var(--bg-raised); border: 1px solid var(--border); cursor: pointer; transition: all var(--dur-fast);
}
.toggle.on { background: var(--down); border-color: var(--down); }
.knob {
  position: absolute; top: 2px; left: 2px; width: 16px; height: 16px; border-radius: 50%;
  background: #fff; transition: left var(--dur-fast);
}
.toggle.on .knob { left: 22px; }
.muted-note { font-size: var(--fs-sm); color: var(--text-sub); }
.time-inp { width: 110px; }
.sel-inp { width: 90px; }
.log {
  white-space: pre-wrap; font-size: var(--fs-xs); font-family: var(--font-mono);
  color: var(--text-sub); background: var(--bg); border: 1px solid var(--border);
  border-radius: var(--radius-sm); padding: var(--sp-3); max-height: 220px; overflow: auto;
  margin: 0;
}
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
