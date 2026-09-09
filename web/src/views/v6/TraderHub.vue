<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import SectionCard from '@/components/ui/SectionCard.vue'
import PageToolbar from '@/components/ui/PageToolbar.vue'
import Drawer from '@/components/ui/Drawer.vue'
import FormField from '@/components/ui/FormField.vue'
import EmptyGuide from '@/components/ui/EmptyGuide.vue'
import LoadingBlock from '@/components/ui/LoadingBlock.vue'
import Icon from '@/components/Icon.vue'
import { useToastStore } from '@/stores/toast'
import { getTraderProfiles, createTraderProfile, updateTraderProfile, deleteTraderProfile } from '@/api'
import type { TraderProfile } from '@/api'
import TraderOverview from '@/views/v6/TraderOverview.vue'
import TraderDetail from '@/views/v6/Trader.vue'

const toast = useToastStore()

type Mode = 'overview' | 'detail'
const mode = ref<Mode>('overview')
const profiles = ref<TraderProfile[]>([])
const currentId = ref<number | null>(null)
const loading = ref(true)
const error = ref('')
const drawerOpen = ref(false)
const adding = ref(false)

// 新建/编辑草稿
const draft = ref({ id: 0, name: '', initial_capital: 100000, model: '', persona: '' })

const current = computed(() => profiles.value.find((p) => p.id === currentId.value) || null)
const hasProfiles = computed(() => profiles.value.length > 0)

async function loadProfiles(silent = false) {
  if (!silent) loading.value = true
  try {
    const r = await getTraderProfiles()
    profiles.value = r.items || []
    if (profiles.value.length && !profiles.value.some((p) => p.id === currentId.value)) {
      currentId.value = profiles.value[0].id
    }
    if (!profiles.value.length) currentId.value = null
    error.value = ''
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
}
onMounted(() => loadProfiles())

function openAdd() {
  draft.value = { id: 0, name: `AI操盘手${profiles.value.length + 1}`, initial_capital: 100000, model: '', persona: '' }
  drawerOpen.value = true
}
function openEdit(p: TraderProfile) {
  draft.value = { id: p.id, name: p.name, initial_capital: p.initial_capital, model: p.model || '', persona: p.persona || '' }
  drawerOpen.value = true
}

async function save() {
  adding.value = true
  try {
    if (draft.value.id) {
      await updateTraderProfile(draft.value.id, {
        name: draft.value.name, model: draft.value.model, persona: draft.value.persona,
      })
      toast.success('已保存')
    } else {
      const r = await createTraderProfile({
        name: draft.value.name, initial_capital: Number(draft.value.initial_capital) || 100000,
        model: draft.value.model, persona: draft.value.persona,
      })
      toast.success(`已创建「${r.profile.name}」，请切到详情跑一次决策`)
    }
    drawerOpen.value = false
    await loadProfiles(true)
  } catch (e) {
    toast.error('保存失败：' + (e instanceof Error ? e.message : String(e)))
  } finally {
    adding.value = false
  }
}

async function remove(p: TraderProfile) {
  if (!window.confirm(`确定删除「${p.name}」？其账户、全部决策与记忆将一并删除（不可恢复）。`)) return
  try {
    await deleteTraderProfile(p.id)
    toast.success(`已删除「${p.name}」`)
    await loadProfiles(true)
  } catch (e) {
    toast.error('删除失败：' + (e instanceof Error ? e.message : String(e)))
  }
}

async function toggleEnabled(p: TraderProfile) {
  try {
    await updateTraderProfile(p.id, { enabled: p.enabled ? 0 : 1 })
    await loadProfiles(true)
  } catch (e) {
    toast.error('操作失败：' + (e instanceof Error ? e.message : String(e)))
  }
}

function select(id: number) {
  currentId.value = id
  mode.value = 'detail'
}
</script>

<template>
  <div class="hub">
    <LoadingBlock v-if="loading && !profiles.length" :rows="4" />

    <EmptyGuide v-else-if="error && !profiles.length" icon="alert" title="加载失败" :desc="error">
      <template #action><button class="ui-btn" @click="loadProfiles()">重试</button></template>
    </EmptyGuide>

    <template v-else>
      <!-- 顶栏：模式 + 交易员选择 + 管理 -->
      <div class="bar">
        <div class="bar__left">
          <div class="seg">
            <button class="seg__btn" :class="{ 'is-on': mode === 'overview' }" @click="mode = 'overview'">
              <Icon name="kline" :size="13" /><span>总览对比</span>
            </button>
            <button class="seg__btn" :class="{ 'is-on': mode === 'detail' }" :disabled="!current" @click="mode = 'detail'">
              <Icon name="agentops" :size="13" /><span>交易员详情</span>
            </button>
          </div>
          <label v-if="hasProfiles" class="sel">
            <select v-model="currentId" class="ui-select" @change="mode = 'detail'">
              <option v-for="p in profiles" :key="p.id" :value="p.id">
                {{ p.name }}{{ p.enabled ? '' : '（停用）' }}
              </option>
            </select>
            <Icon v-if="current" name="settings" :size="12" class="sel__gear" @click="openEdit(current)" />
            <span v-if="current" class="sel__model">{{ current.model || '默认模型' }}</span>
          </label>
        </div>
        <div class="bar__right">
          <button class="ui-btn" @click="openAdd"><Icon name="plus" :size="14" /><span>新建交易员</span></button>
        </div>
      </div>

      <!-- 交易员卡片条 -->
      <div v-if="hasProfiles" class="chips">
        <button
          v-for="p in profiles"
          :key="p.id"
          class="chip"
          :class="{ 'is-on': p.id === currentId && mode === 'detail', 'is-off': !p.enabled }"
          :style="{ '--chip-accent': p.id === currentId ? 'var(--accent)' : 'var(--text-faint)' }"
          @click="select(p.id)"
        >
          <span class="chip__name">{{ p.name }}</span>
          <span class="chip__model">{{ p.model || '默认' }}</span>
          <span class="chip__act">
            <button class="link" title="编辑" @click.stop="openEdit(p)"><Icon name="edit" :size="12" /></button>
            <button class="link" :title="p.enabled ? '停用' : '启用'" @click.stop="toggleEnabled(p)">
              <Icon :name="p.enabled ? 'minus' : 'plus'" :size="12" />
            </button>
            <button class="link link--danger" title="删除" @click.stop="remove(p)"><Icon name="trash" :size="12" /></button>
          </span>
        </button>
      </div>

      <EmptyGuide v-if="!hasProfiles" icon="agentops" title="还没有交易员" desc="新建一个：它会有自己的账户、模型与记忆，与其它交易员完全独立。">
        <template #action><button class="ui-btn ui-btn--primary" @click="openAdd">新建交易员</button></template>
      </EmptyGuide>

      <!-- 内容 -->
      <TraderOverview v-if="mode === 'overview'" @select="select" />
      <TraderDetail v-else-if="mode === 'detail' && currentId" :profile-id="currentId" :key="currentId" />
    </template>

    <!-- 新建/编辑抽屉 -->
    <Drawer :open="drawerOpen" :title="draft.id ? '编辑交易员' : '新建交易员'" desc="每个交易员拥有独立账户与长期记忆" :width="440" @update:open="drawerOpen = $event">
      <div class="form">
        <FormField label="名称" hint="如果不填会用默认名">
          <input v-model="draft.name" class="ui-input" placeholder="如：价值派 / 趋势派 / 激进一号" />
        </FormField>
        <FormField label="初始本金（元）">
          <input v-model.number="draft.initial_capital" class="ui-input" type="number" min="10000" step="10000" />
        </FormField>
        <FormField label="模型" hint="留空使用全局默认模型（设置 → AI）">
          <input v-model="draft.model" class="ui-input" placeholder="如 deepseek-v4-flash-vision-exp" />
        </FormField>
        <FormField label="人设 / 风格说明" hint="可选；不预设时由 AI 自己形成风格">
          <textarea v-model="draft.persona" class="ui-input" rows="4" placeholder="（可选）" />
        </FormField>
        <div class="form__foot">
          <button class="ui-btn" @click="drawerOpen = false">取消</button>
          <button class="ui-btn ui-btn--primary" :disabled="adding" @click="save">{{ adding ? '保存中…' : '保存' }}</button>
        </div>
      </div>
    </Drawer>
  </div>
</template>

<style scoped>
.hub { display: flex; flex-direction: column; gap: var(--sp-4); }

.bar { display: flex; align-items: center; justify-content: space-between; gap: var(--sp-3); flex-wrap: wrap; }
.bar__left { display: flex; align-items: center; gap: var(--sp-3); flex-wrap: wrap; }
.bar__right { display: flex; gap: var(--sp-2); }

.seg { display: inline-flex; border: 1px solid var(--border); border-radius: var(--radius-sm); overflow: hidden; }
.seg__btn { display: inline-flex; align-items: center; gap: 6px; background: none; border: none; padding: 6px 14px; font-size: var(--fs-sm); color: var(--text-sub); cursor: pointer; }
.seg__btn.is-on { background: var(--panel-2); color: var(--accent); font-weight: 600; }
.seg__btn:disabled { opacity: 0.5; cursor: not-allowed; }

.sel { display: inline-flex; align-items: center; gap: 8px; }
.ui-select { min-width: 170px; }
.sel__gear { color: var(--text-faint); cursor: pointer; }
.sel__gear:hover { color: var(--accent); }
.sel__model { font-size: var(--fs-xs); color: var(--text-faint); }

.chips { display: flex; gap: var(--sp-2); flex-wrap: wrap; }
.chip {
  display: inline-flex; align-items: center; gap: 8px;
  padding: 6px 12px; border: 1px solid var(--border); border-radius: 999px;
  background: var(--panel-2); color: var(--text-sub); font-size: var(--fs-sm); cursor: pointer;
}
.chip.is-on { border-color: var(--accent); color: var(--accent); font-weight: 600; }
.chip.is-off { opacity: 0.55; }
.chip__model { font-size: var(--fs-xs); color: var(--text-faint); }
.chip__act { display: inline-flex; gap: 6px; }
.link { background: none; border: none; color: var(--text-faint); cursor: pointer; padding: 0; display: inline-flex; }
.link:hover { color: var(--accent); }
.link--danger:hover { color: var(--up); }

.form { display: flex; flex-direction: column; gap: var(--sp-4); }
.form__foot { display: flex; justify-content: flex-end; gap: var(--sp-2); margin-top: var(--sp-2); }
textarea.ui-input { resize: vertical; font-family: inherit; }
</style>
