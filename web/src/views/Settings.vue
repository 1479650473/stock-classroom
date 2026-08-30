<script setup lang="ts">
import { ref, onMounted } from 'vue'
import PageHeader from '@/components/PageHeader.vue'
import Card from '@/components/Card.vue'
import Icon from '@/components/Icon.vue'
import { useAppStore } from '@/stores/app'
import { useToastStore } from '@/stores/toast'
import { getSettings, saveSettings, testLlm } from '@/api'

const app = useAppStore()
const toast = useToastStore()

const themeOptions = [
  { key: 'graphite' as const, label: '石墨', color: '#D4A574' },
  { key: 'obsidian' as const, label: '黑曜', color: '#8B5CF6' },
  { key: 'ivory' as const, label: '象牙', color: '#2563EB' },
]
const fontOptions = [12, 13, 14, 15, 16]
const fontSizeOptions = fontOptions

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
})

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
      agent: { api_base: agentBase.value, api_key: agentKey.value, model: agentModel.value },
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
        <label class="lbl">API Key</label>
        <input v-model="agentKey" class="inp" type="password" placeholder="sk-..." />
      </div>
      <div class="field">
        <label class="lbl">模型</label>
        <input v-model="agentModel" class="inp" placeholder="deepseek-chat" />
      </div>
      <div class="actions">
        <button class="btn ghost" @click="testConnection" :disabled="testingLlm">
          <Icon v-if="testingLlm" name="refresh" :size="14" class="spin" />
          {{ testingLlm ? '测试中…' : '测试连接' }}
        </button>
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
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
