<script setup lang="ts">
import { ref, computed, reactive, onMounted } from 'vue'
import PageHeader from '@/components/PageHeader.vue'
import Card from '@/components/Card.vue'
import Icon from '@/components/Icon.vue'
import { useAppStore } from '@/stores/app'
import { useToastStore } from '@/stores/toast'
import { getSettings, saveSettings, testLlm, getScheduler, saveScheduler, schedulerRunNow } from '@/api'
import {
  isTauri, getDesktopPrefs, setDesktopPrefs, getAutostart, setAutostart, hideToTray,
} from '@/lib/tauri'
import {
  THEMES, DENSITIES, RADII, MOTIONS, BACKDROPS, FONT_SIZE_OPTIONS,
  type ThemeKey, type Density, type Radius, type Motion, type Backdrop,
} from '@/lib/appearance'

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

// ─── 桌面（外壳）行为 ───
const desk = reactive({
  autostart: false,
  close_to_tray: true,
  system_notify: true,
  data_dir: '',
  isDesktop: false,
})
const deskBusy = ref(false)

async function loadDesktop() {
  desk.isDesktop = isTauri()
  if (!desk.isDesktop) return
  const p = await getDesktopPrefs()
  if (p) {
    desk.close_to_tray = p.close_to_tray
    desk.system_notify = p.system_notify
    desk.data_dir = p.data_dir || ''
  }
  desk.autostart = await getAutostart()
}

async function saveDesktop() {
  if (!desk.isDesktop) {
    toast.info('桌面行为只在安装版客户端里生效')
    return
  }
  deskBusy.value = true
  try {
    await setDesktopPrefs({
      close_to_tray: desk.close_to_tray,
      system_notify: desk.system_notify,
      data_dir: desk.data_dir.trim() || null,
    })
    const on = await setAutostart(desk.autostart)
    desk.autostart = on
    toast.success('桌面设置已保存')
  } catch (e: unknown) {
    toast.error('保存失败：' + (e instanceof Error ? e.message : String(e)))
  } finally { deskBusy.value = false }
}

/* 外观：主题清单与各维度选项统一来自 @/lib/appearance（单一声明源），
   颜色定义在 styles/tokens.css。这里只做展示与写入。 */
const appearanceBusy = ref(false)
function pickTheme(k: ThemeKey) { app.setTheme(k) }
function pickDensity(k: Density) { app.setDensity(k) }
function pickRadius(k: Radius) { app.setRadius(k) }
function pickMotion(k: Motion) { app.setMotion(k) }
function pickBackdrop(k: Backdrop) { app.setBackdrop(k) }
function resetAppearance() {
  if (!confirm('恢复默认外观？（主题=石墨、标准密度/圆角、完整动效、网格背景；字号=14px）')) return
  app.resetAppearance()
  toast.success('已恢复默认外观')
}
/** 当前主题的展示信息（用于「当前：xxx」提示） */
const currentTheme = computed(() => THEMES.find((t) => t.key === app.theme))

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
    // 外观（主题 + 4 个维度）已由 stores/app.ts 的 init() 从同一份 settings 统一应用，
    // 这里不再重复 set（否则会触发多余的持久化写回）。
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
      <div class="sec-head">
        <div>
          <h2 class="sec-title">外观</h2>
          <p class="sec-sub">
            所有外观项即时生效（无需保存）。主题决定配色；密度 / 圆角 / 动效 / 背景与主题互相独立。
          </p>
        </div>
        <button class="btn btn--ghost" @click="resetAppearance" :disabled="appearanceBusy">
          <Icon name="refresh" :size="14" /> 恢复默认
        </button>
      </div>

      <!-- 主题：按深色/浅色分组，用色板预览而不是纯文字 -->
      <div class="row row--top">
        <label class="lbl">主题</label>
        <div class="opts opts--grow">
          <div v-for="fam in (['dark', 'light'] as const)" :key="fam" class="theme-group">
            <span class="theme-group__label">{{ fam === 'dark' ? '深色' : '浅色' }}</span>
            <div class="theme-grid">
              <button
                v-for="t in THEMES.filter((x) => x.family === fam)"
                :key="t.key"
                class="theme-card"
                :class="{ active: app.theme === t.key }"
                :title="t.hint"
                :aria-pressed="app.theme === t.key"
                @click="pickTheme(t.key)"
              >
                <span class="theme-card__swatch">
                  <i v-for="(c, i) in t.swatch" :key="i" :style="{ background: c }" />
                </span>
                <span class="theme-card__label">
                  {{ t.label }}
                  <Icon v-if="app.theme === t.key" name="check" :size="12" />
                </span>
              </button>
            </div>
          </div>
          <p class="hint">当前：{{ currentTheme?.label }} —— {{ currentTheme?.hint }}</p>
        </div>
      </div>

      <!-- 密度 -->
      <div class="row">
        <label class="lbl">密度</label>
        <div class="opts">
          <button
            v-for="d in DENSITIES" :key="d.key"
            class="chip" :class="{ active: app.density === d.key }"
            :title="d.hint" @click="pickDensity(d.key)"
          >{{ d.label }}</button>
        </div>
        <span class="hint hint--inline">{{ DENSITIES.find((x) => x.key === app.density)?.hint }}</span>
      </div>

      <!-- 圆角 -->
      <div class="row">
        <label class="lbl">圆角</label>
        <div class="opts">
          <button
            v-for="r in RADII" :key="r.key"
            class="chip" :class="{ active: app.radius === r.key }"
            :title="r.hint" @click="pickRadius(r.key)"
          >{{ r.label }}</button>
        </div>
        <span class="hint hint--inline">{{ RADII.find((x) => x.key === app.radius)?.hint }}</span>
      </div>

      <!-- 动效 -->
      <div class="row">
        <label class="lbl">动效</label>
        <div class="opts">
          <button
            v-for="m in MOTIONS" :key="m.key"
            class="chip" :class="{ active: app.motion === m.key }"
            :title="m.hint" @click="pickMotion(m.key)"
          >{{ m.label }}</button>
        </div>
        <span class="hint hint--inline">{{ MOTIONS.find((x) => x.key === app.motion)?.hint }}</span>
      </div>

      <!-- 背景纹理 -->
      <div class="row">
        <label class="lbl">背景</label>
        <div class="opts">
          <button
            v-for="b in BACKDROPS" :key="b.key"
            class="chip" :class="{ active: app.backdrop === b.key }"
            :title="b.hint" @click="pickBackdrop(b.key)"
          >{{ b.label }}</button>
        </div>
        <span class="hint hint--inline">{{ BACKDROPS.find((x) => x.key === app.backdrop)?.hint }}</span>
      </div>

      <!-- 字号 -->
      <div class="row">
        <label class="lbl">字号</label>
        <div class="opts">
          <button
            v-for="f in FONT_SIZE_OPTIONS" :key="f"
            class="chip" :class="{ active: app.fontSize === f }"
            @click="app.setFontSize(f)"
          >{{ f }}px</button>
        </div>
        <span class="hint hint--inline">整体缩放界面字号（不影响密度）</span>
      </div>
    </Card>

    <Card class="sec">
      <h2 class="sec-title">桌面</h2>
      <div class="row">
        <label class="lbl">开机自启</label>
        <div class="opts">
          <label class="switch">
            <input v-model="desk.autostart" type="checkbox" />
            <span class="switch__track"><span class="switch__thumb" /></span>
            <span class="switch__text">{{ desk.autostart ? '随系统启动' : '关闭' }}</span>
          </label>
        </div>
      </div>
      <div class="row">
        <label class="lbl">关闭按钮</label>
        <div class="opts">
          <label class="switch">
            <input v-model="desk.close_to_tray" type="checkbox" />
            <span class="switch__track"><span class="switch__thumb" /></span>
            <span class="switch__text">{{ desk.close_to_tray ? '最小化到托盘（后台继续跑任务）' : '直接退出程序' }}</span>
          </label>
        </div>
      </div>
      <div class="row">
        <label class="lbl">数据目录</label>
        <div class="opts" style="flex:1; min-width: 260px">
          <input
            v-model="desk.data_dir"
            class="inp"
            placeholder="留空 = 安装目录下的 data\"
            spellcheck="false"
          />
        </div>
      </div>
      <div class="row">
        <label class="lbl">系统通知</label>
        <div class="opts">
          <label class="switch">
            <input v-model="desk.system_notify" type="checkbox" />
            <span class="switch__track"><span class="switch__thumb" /></span>
            <span class="switch__text">{{ desk.system_notify ? '任务完成/失败时通知我' : '关闭' }}</span>
          </label>
        </div>
      </div>
      <div class="actions">
        <button class="btn" :disabled="deskBusy" @click="saveDesktop">
          {{ deskBusy ? '保存中…' : '保存桌面设置' }}
        </button>
        <button class="btn ghost" @click="hideToTray()">立即最小化到托盘</button>
      </div>
      <p class="muted small">
        数据目录指向已有行情库可避免重新下载；修改后<strong>需重启应用</strong>生效。
      </p>
      <p v-if="!desk.isDesktop" class="muted small">当前在浏览器里预览，桌面行为需在安装版客户端中生效。</p>
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
/* 设置页容器：原来限宽 640px，在 1600 宽屏上只占约 40%，
   右侧大片留白而主题网格被迫换行 —— 放宽并让卡片自适应。 */
.settings { max-width: 1080px; }
.sec {
  margin-bottom: var(--sp-5);
  padding: var(--sp-5);
}
.sec-title { font-size: var(--fs-lg); font-weight: 600; color: var(--text); margin: 0 0 var(--sp-4); }

/* ---- 外观卡片（2026-10-15）---- */
.sec-head {
  display: flex; align-items: flex-start; justify-content: space-between;
  gap: var(--sp-4); margin-bottom: var(--sp-5);
}
.sec-head .sec-title { margin-bottom: var(--sp-1); }
.sec-sub { margin: 0; font-size: var(--fs-sm); color: var(--text-sub); line-height: 1.5; }

/* 外观行：标签**顶对齐**（不是垂直居中）——
   主题块有 3 行，若居中会让标签飘到中间，上下各留一大段空白。 */
.row--top .lbl { padding-top: 3px; }
.opts--grow { flex: 1; min-width: 0; flex-direction: column; gap: var(--sp-4); }

.theme-group { display: flex; flex-direction: column; gap: var(--sp-2); }
.theme-group__label {
  font-size: var(--fs-xs); color: var(--text-faint);
  text-transform: uppercase; letter-spacing: 0.08em;
}
/* 主题网格：8 个主题自适应铺开（宽屏 5 列、窄屏 1~2 列），避免只有两三个一行。 */
.theme-grid {
  display: grid; gap: var(--sp-3);
  grid-template-columns: repeat(auto-fill, minmax(108px, 1fr));
}
/* 主题卡：色板预览比纯文字更能说明"长什么样" */
.theme-card {
  display: flex; flex-direction: column; gap: 7px;
  padding: 9px; cursor: pointer; text-align: left;
  background: var(--bg-panel); color: var(--text-sub);
  border: 1px solid var(--border); border-radius: var(--radius-md);
  transition: border-color var(--dur-fast), transform var(--dur-fast), color var(--dur-fast);
}
.theme-card:hover { border-color: var(--border-strong); transform: translateY(-1px); }
.theme-card.active { border-color: var(--gold); color: var(--text); box-shadow: 0 0 0 1px var(--gold); }
.theme-card__swatch {
  display: flex; height: 30px; border-radius: var(--radius-sm);
  overflow: hidden; border: 1px solid var(--border-soft);
}
.theme-card__swatch i { flex: 1; }
.theme-card__label {
  display: inline-flex; align-items: center; justify-content: space-between;
  font-size: var(--fs-sm); gap: 4px;
}
.theme-card.active .theme-card__label { color: var(--gold); }

/* 通用小胶囊按钮（密度/圆角/动效/背景/字号共用） */
.chip {
  padding: 6px 13px; cursor: pointer; font-size: var(--fs-sm);
  background: transparent; color: var(--text-sub);
  border: 1px solid var(--border); border-radius: var(--radius-pill);
  transition: border-color var(--dur-fast), color var(--dur-fast), background var(--dur-fast);
}
.chip:hover { border-color: var(--border-strong); color: var(--text); }
.chip.active { border-color: var(--gold); color: var(--gold); background: var(--gold-dim); }

.hint { margin: 0; font-size: var(--fs-xs); color: var(--text-faint); line-height: 1.5; }
.hint--inline { flex: 1; min-width: 0; }

.btn--ghost {
  background: transparent; color: var(--text-sub);
  border: 1px solid var(--border); border-radius: var(--radius-sm);
  padding: 7px 13px; font-size: var(--fs-sm); cursor: pointer;
  display: inline-flex; align-items: center; gap: var(--sp-2);
}
.btn--ghost:hover { border-color: var(--border-strong); color: var(--text); }

.row { display: flex; align-items: center; gap: var(--sp-4); margin-bottom: var(--sp-3); }
/* ⚠️ 顺序要紧：`.row--top` 必须排在基础 `.row` **之后**。
   同为单类选择器、特异性相同 → 后写者胜。早期版本把 .row--top 写在前面，
   被后面的 `.row{align-items:center}` 覆盖，导致标签仍然垂直居中（实测踩过）。 */
.row--top { align-items: flex-start; }
.lbl { font-size: var(--fs-sm); color: var(--text-sub); min-width: 80px; }
.opts { display: flex; gap: var(--sp-2); flex-wrap: wrap; }
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

/* 桌面设置：主题化开关（非系统默认勾选框） */
.switch { display: inline-flex; align-items: center; gap: 10px; cursor: pointer; }
.switch input { position: absolute; opacity: 0; pointer-events: none; }
.switch__track {
  position: relative;
  width: 38px;
  height: 22px;
  border-radius: var(--radius-pill);
  background: var(--bg-overlay);
  border: 1px solid var(--border);
  transition: background var(--dur-fast) var(--ease), border-color var(--dur-fast) var(--ease);
  flex: none;
}
.switch__thumb {
  position: absolute;
  top: 2px;
  left: 2px;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: var(--text-faint);
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.25);
  transition: transform var(--dur) var(--ease-out), background var(--dur-fast) var(--ease);
}
.switch input:checked + .switch__track { background: var(--gold-dim); border-color: var(--gold); }
.switch input:checked + .switch__track .switch__thumb { transform: translateX(16px); background: var(--gold); }
.switch__text { font-size: var(--fs-sm); color: var(--text-sub); }
.small { font-size: var(--fs-xs); }
</style>