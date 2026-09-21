<script setup lang="ts">
import { computed, onActivated, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import AppPage from '@/components/ui/AppPage.vue'
import SectionCard from '@/components/ui/SectionCard.vue'
import StatTile from '@/components/ui/StatTile.vue'
import EmptyGuide from '@/components/ui/EmptyGuide.vue'
import LoadingBlock from '@/components/ui/LoadingBlock.vue'
import Icon from '@/components/Icon.vue'
import Drawer from '@/components/ui/Drawer.vue'
import { usePersistedRef } from '@/composables/usePersistedRef'
import { getBootstrap, getOverview, getPicks } from '@/api'
import type { Bootstrap, OverviewData, PickItem } from '@/api'
import { useJobsStore } from '@/stores/jobs'

const router = useRouter()
const jobs = useJobsStore()
const data = ref<OverviewData | null>(null)
const picks = ref<PickItem[]>([])
const boot = ref<Bootstrap | null>(null)
const loading = ref(true)
const error = ref('')

const totalAssets = computed(() => data.value?.accounts?.reduce((s, a) => s + a.total_assets, 0) ?? 0)
const totalProfit = computed(() => data.value?.accounts?.reduce((s, a) => s + a.total_profit, 0) ?? 0)
const totalPositions = computed(() => data.value?.accounts?.reduce((s, a) => s + a.positions, 0) ?? 0)
const totalBalance = computed(() => data.value?.accounts?.reduce((s, a) => s + a.balance, 0) ?? 0)

async function load(fresh = false) {
  // 已有数据时不显示整页加载态：直接渲染旧数据 + 后台静默刷新（切回页面零等待）
  loading.value = !data.value
  error.value = ''
  try {
    const [ov, pk, bs] = await Promise.allSettled([
      getOverview(fresh), getPicks(5, fresh), getBootstrap(fresh),
    ])
    if (ov.status === 'fulfilled') data.value = ov.value
    else throw ov.reason
    if (pk.status === 'fulfilled') picks.value = pk.value.items
    if (bs.status === 'fulfilled') boot.value = bs.value
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
}
onMounted(() => load())
// 从别的页面切回来：若缓存已过期就静默刷新（TTL 内则是零请求）
onActivated(() => load())

// ── 数据新鲜度：引导用户手动更新数据 ──
function fmtDate(s: string) {
  return `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)}`
}

const fresh = computed(() => {
  const b = boot.value
  if (!b) return null
  const max = b.kline?.max
  if (b.needs_init || !max) {
    return { level: 'bad' as const, label: '尚未初始化', days: null as number | null, max: '—', rows: 0 }
  }
  const s = String(max).replace(/-/g, '')
  const d = new Date(Number(s.slice(0, 4)), Number(s.slice(4, 6)) - 1, Number(s.slice(6, 8)))
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const days = Math.max(0, Math.round((today.getTime() - d.getTime()) / 86400000))
  const base = { days, max: fmtDate(s), rows: b.kline?.rows ?? null }
  if (days <= 3) return { ...base, level: 'ok' as const, label: '数据较新' }
  if (days <= 7) return { ...base, level: 'warn' as const, label: '建议更新' }
  return { ...base, level: 'bad' as const, label: '数据过期' }
})

const updating = computed(() => !!jobs.activeByKind('pipeline'))
const updateJob = computed(() => jobs.activeByKind('pipeline'))

function goUpdate() {
  router.push('/data?tab=pipeline')
}

function go(path: string) { router.push(path) }

function fmtMoney(v: number) {
  if (Math.abs(v) >= 1e8) return (v / 1e8).toFixed(2) + '亿'
  if (Math.abs(v) >= 1e4) return (v / 1e4).toFixed(2) + '万'
  return v.toLocaleString(undefined, { maximumFractionDigits: 2 })
}
function fmtPct(v: number) { return (v >= 0 ? '+' : '') + v.toFixed(2) + '%' }

/** 工作台模块可见性：可配置 + 本地记忆 */
const modsOpen = ref(false)
const MODULE_DEFS = [
  { key: 'metrics', label: '账户概览', desc: '总资产 / 盈亏 / 持仓 / 可用余额' },
  { key: 'picks', label: '今日关注', desc: '多因子评分 Top 5' },
  { key: 'market', label: '市场速览', desc: '主要指数涨跌' },
  { key: 'fresh', label: '数据状态', desc: '行情新鲜度与更新入口' },
  { key: 'quick', label: '快捷流程', desc: '常用操作一键直达' },
] as const
type ModuleKey = (typeof MODULE_DEFS)[number]['key']
const mods = usePersistedRef<Record<ModuleKey, boolean>>('dashboard.modules', {
  metrics: true, picks: true, market: true, fresh: true, quick: true,
})
function resetMods() {
  mods.value = { metrics: true, picks: true, market: true, fresh: true, quick: true }
}

const QUICK = [
  { icon: 'refresh', label: '更新数据', desc: '拉取最新 K 线与基本面', to: '/data' },
  { icon: 'picks', label: '运行选股', desc: '多因子评分生成候选', to: '/trade?tab=picks' },
  { icon: 'backtest', label: '策略回测', desc: '验证策略历史表现', to: '/strategy?tab=backtest' },
  { icon: 'play', label: '策略回放', desc: '逐日复盘买卖点', to: '/strategy?tab=replay' },
]
</script>

<template>
  <AppPage title="工作台" subtitle="账户、关注与快捷操作，一眼掌握">
    <template #actions>
      <button class="ui-btn" title="自定义工作台模块" @click="modsOpen = true">
        <Icon name="settings" :size="14" /><span>自定义</span>
      </button>
      <button class="ui-btn" @click="load(true)"><Icon name="refresh" :size="14" /><span>刷新</span></button>
      <button class="ui-btn ui-btn--primary" @click="go('/trade?tab=picks')">
        <Icon name="picks" :size="14" /><span>去选股</span>
      </button>
    </template>

    <LoadingBlock v-if="loading && !data" :rows="6" />

    <EmptyGuide v-else-if="error && !data" icon="alert" title="加载失败" :desc="error">
      <template #action><button class="ui-btn" @click="load(true)">重试</button></template>
    </EmptyGuide>

    <template v-else-if="data">
      <!-- 账户概览 -->
      <div v-if="mods.metrics" class="metrics">
        <StatTile
          label="总资产"
          :value="fmtMoney(totalAssets)"
          :raw="totalAssets"
          :format="fmtMoney"
          icon="wallet"
        />
        <StatTile
          label="总盈亏"
          :value="fmtMoney(totalProfit)"
          :raw="totalProfit"
          :format="fmtMoney"
          :trend="totalProfit >= 0 ? 'up' : 'down'"
          :hint="totalAssets ? fmtPct((totalProfit / (totalAssets - totalProfit)) * 100) : '—'"
          :hint-trend="totalProfit >= 0 ? 'up' : 'down'"
        />
        <StatTile label="持仓" :value="totalPositions" unit="只" :raw="totalPositions" :format="(n: number) => String(Math.round(n))" />
        <StatTile
          label="可用余额"
          :value="fmtMoney(totalBalance)"
          :raw="totalBalance"
          :format="fmtMoney"
        />
        <StatTile
          v-if="data.strategy"
          label="最优策略"
          :value="data.strategy.name"
          :hint="`总收益 ${fmtPct((data.strategy.total_return ?? 0) * 100)} · 夏普 ${(data.strategy.sharpe ?? 0).toFixed(2)}`"
          :hint-trend="(data.strategy.total_return ?? 0) >= 0 ? 'up' : 'down'"
        />
      </div>

      <div v-if="mods.picks || mods.market" class="cols" :class="{ 'cols--even': !(mods.picks && mods.market) }">
        <!-- 今日关注 -->
        <SectionCard v-if="mods.picks" title="今日关注" desc="多因子评分 Top 5">
          <template #actions>
            <button class="ui-btn ui-btn--sm ui-btn--ghost" @click="go('/trade?tab=picks')">
              全部<Icon name="chevron-right" :size="13" />
            </button>
          </template>
          <div v-if="picks.length" class="watchlist stagger">
            <button
              v-for="(p, i) in picks"
              :key="p.code"
              class="watch-item"
              @click="go(`/market?tab=stock&code=${p.code}`)"
            >
              <span class="watch-item__rank">{{ i + 1 }}</span>
              <span class="watch-item__name">{{ p.name }}</span>
              <span class="watch-item__code num">{{ p.code }}</span>
              <span class="watch-item__chg num" :class="p.change_pct >= 0 ? 'up' : 'down'">{{ fmtPct(p.change_pct) }}</span>
              <span class="watch-item__score num">{{ p.score.toFixed(1) }}</span>
            </button>
          </div>
          <EmptyGuide
            v-else
            icon="picks"
            title="还没有选股结果"
            desc="运行一次多因子扫描，就能在这里看到今日候选。"
          >
            <template #action>
              <button class="ui-btn ui-btn--primary" @click="go('/trade?tab=picks')">去选股</button>
            </template>
          </EmptyGuide>
        </SectionCard>

        <!-- 市场速览 -->
        <SectionCard v-if="mods.market" title="市场速览" desc="主要指数">
          <template #actions>
            <button class="ui-btn ui-btn--sm ui-btn--ghost" @click="go('/market')">
              行情<Icon name="chevron-right" :size="13" />
            </button>
          </template>
          <div v-if="data.market?.length" class="indices stagger">
            <div v-for="idx in data.market" :key="idx.code" class="index-item">
              <div class="index-item__name">{{ idx.name }}</div>
              <div class="index-item__price num">{{ idx.price.toLocaleString() }}</div>
              <div class="index-item__chg num" :class="idx.change_pct >= 0 ? 'up' : 'down'">{{ fmtPct(idx.change_pct) }}</div>
            </div>
          </div>
          <EmptyGuide v-else icon="market" title="暂无行情数据" />
        </SectionCard>
      </div>

      <!-- 数据新鲜度 -->
      <SectionCard v-if="mods.fresh && fresh" title="数据状态" desc="行情数据更新时间与新鲜度，过期会影响选股与回测">
        <template #actions>
          <button class="ui-btn ui-btn--sm" :disabled="updating" @click="goUpdate">
            <Icon :name="updating ? 'refresh' : 'pipeline'" :size="13" :class="{ spin: updating }" />
            <span>{{ updating ? '更新中…' : '去更新' }}</span>
          </button>
        </template>
        <div class="fresh" :class="'fresh--' + fresh.level">
          <span class="fresh__dot" />
          <div class="fresh__main">
            <div class="fresh__label">{{ fresh.label }}</div>
            <div class="fresh__desc">
              最新交易日 <b class="mono">{{ fresh.max }}</b>
              <template v-if="fresh.days !== null"> · 距今 {{ fresh.days }} 天</template>
              <template v-if="fresh.rows != null"> · 共 {{ (fresh.rows / 1e6).toFixed(1) }}M 行</template>
            </div>
            <div v-if="updating" class="fresh__progress">
              {{ updateJob?.msg }} <span class="mono">{{ updateJob?.pct }}%</span>
            </div>
          </div>
        </div>
        <p v-if="fresh.level === 'bad' && !updating" class="fresh__hint">
          数据过期会让选股、回测与回放的结果偏离真实市场。点“去更新”按引导完成数据更新。
        </p>
      </SectionCard>

      <!-- 快捷流程 -->
      <SectionCard v-if="mods.quick" title="快捷流程" desc="常用操作一键直达">
        <div class="quick-grid">
          <button v-for="q in QUICK" :key="q.label" class="quick-item" @click="go(q.to)">
            <span class="quick-item__icon"><Icon :name="q.icon" :size="18" /></span>
            <span class="quick-item__text">
              <span class="quick-item__label">{{ q.label }}</span>
              <span class="quick-item__desc">{{ q.desc }}</span>
            </span>
            <Icon name="chevron-right" :size="14" class="quick-item__arrow" />
          </button>
        </div>
      </SectionCard>

      <p class="as-of faint">数据时间：{{ data.as_of }}</p>
    </template>

    <!-- 工作台自定义：显示/隐藏模块（本地记忆） -->
    <Drawer v-model:open="modsOpen" title="自定义工作台" desc="选择要显示的模块，设置会被记住" :width="360">
      <div class="mods">
        <label v-for="m in MODULE_DEFS" :key="m.key" class="mods__item">
          <span class="mods__text">
            <span class="mods__label">{{ m.label }}</span>
            <span class="mods__desc">{{ m.desc }}</span>
          </span>
          <input v-model="mods[m.key]" type="checkbox" class="mods__switch" />
        </label>
      </div>
      <template #footer>
        <button class="ui-btn ui-btn--sm" @click="resetMods">全部显示</button>
        <button class="ui-btn ui-btn--primary ui-btn--sm" @click="modsOpen = false">完成</button>
      </template>
    </Drawer>
  </AppPage>
</template>

<style scoped>
/* 今日关注：前三名给徽章色，行悬停轻微右移 */
.watch-item__rank {
  display: grid;
  place-items: center;
  width: 20px;
  height: 20px;
  border-radius: var(--radius-sm);
  background: var(--bg-overlay);
  color: var(--text-faint);
  font-size: var(--fs-xs);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  flex: none;
}
.watch-item:nth-child(1) .watch-item__rank {
  background: var(--gold-dim);
  color: var(--gold);
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--gold) 35%, transparent);
}
.watch-item:nth-child(2) .watch-item__rank,
.watch-item:nth-child(3) .watch-item__rank {
  background: color-mix(in srgb, var(--text-sub) 16%, transparent);
  color: var(--text-sub);
}
.watch-item { transition: background var(--dur-fast) var(--ease), transform var(--dur-fast) var(--ease); }
.watch-item:hover { transform: translateX(2px); }
/* .metrics / .cols 已收敛到全局样式（styles/base.css） */

/* 自定义抽屉：模块开关 */
.mods { display: flex; flex-direction: column; gap: 2px; }
.mods__item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-4);
  padding: var(--sp-3) var(--sp-2);
  border-bottom: 1px solid var(--border-soft);
  cursor: pointer;
}
.mods__item:last-child { border-bottom: none; }
.mods__item:hover { background: var(--bg-hover); border-radius: var(--radius-md); }
.mods__text { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.mods__label { font-size: var(--fs-md); color: var(--text); }
.mods__desc { font-size: var(--fs-xs); color: var(--text-faint); }
/* 开关样式（沿用系统勾选框但套上主题色） */
.mods__switch {
  flex: none;
  width: 34px;
  height: 20px;
  appearance: none;
  border-radius: var(--radius-pill);
  background: var(--bg-overlay);
  border: 1px solid var(--border);
  position: relative;
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease), border-color var(--dur-fast) var(--ease);
}
.mods__switch::after {
  content: '';
  position: absolute;
  top: 2px;
  left: 2px;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: var(--text-faint);
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.25);
  transition: transform var(--dur) var(--ease-out), background var(--dur-fast) var(--ease);
}
.mods__switch:checked { background: var(--gold-dim); border-color: var(--gold); }
.mods__switch:checked::after { transform: translateX(14px); background: var(--gold); }

.watchlist { display: flex; flex-direction: column; }
.watch-item {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  padding: 10px var(--sp-5);
  border: 0;
  border-bottom: 1px solid var(--border-soft);
  background: transparent;
  color: var(--text);
  font-size: var(--fs-md);
  text-align: left;
  cursor: pointer;
  transition: background var(--dur-fast);
}
.watch-item:last-child { border-bottom: 0; }
.watch-item:hover { background: var(--bg-hover); }
.watch-item__rank {
  width: 20px;
  height: 20px;
  display: grid;
  place-items: center;
  border-radius: var(--radius-pill);
  background: var(--bg-overlay);
  color: var(--text-faint);
  font-size: var(--fs-xs);
  flex: none;
}
.watch-item__name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.watch-item__code { color: var(--text-faint); font-size: var(--fs-sm); }
.watch-item__chg { width: 68px; text-align: right; }
.watch-item__score { width: 44px; text-align: right; color: var(--gold); font-weight: 600; }

.indices { display: flex; flex-direction: column; }
.index-item {
  display: flex;
  align-items: baseline;
  gap: var(--sp-3);
  padding: 10px var(--sp-5);
  border-bottom: 1px solid var(--border-soft);
}
.index-item:last-child { border-bottom: 0; }
.index-item__name { flex: 1; color: var(--text-sub); font-size: var(--fs-sm); }
.index-item__price { width: 110px; text-align: right; font-size: var(--fs-lg); font-weight: 600; }
.index-item__chg { width: 72px; text-align: right; font-size: var(--fs-sm); }

.quick-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); }
.quick-item {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  padding: var(--sp-4) var(--sp-5);
  border: 0;
  border-right: 1px solid var(--border-soft);
  background: transparent;
  color: var(--text);
  text-align: left;
  cursor: pointer;
  transition: background var(--dur-fast);
}
.quick-item:last-child { border-right: 0; }
.quick-item:hover { background: var(--bg-hover); }
.quick-item__icon {
  display: grid;
  place-items: center;
  width: 38px;
  height: 38px;
  border-radius: var(--radius-md);
  background: var(--gold-dim);
  color: var(--gold);
  flex: none;
}
.quick-item__text { display: flex; flex-direction: column; gap: 2px; flex: 1; min-width: 0; }
.quick-item__label { font-size: var(--fs-md); font-weight: 600; }
.quick-item__desc { font-size: var(--fs-xs); color: var(--text-faint); }
.quick-item__arrow { color: var(--text-faint); flex: none; }
.as-of { margin: 0; font-size: var(--fs-xs); }

.fresh {
  display: flex;
  align-items: flex-start;
  gap: var(--sp-3);
  padding: var(--sp-4) var(--sp-5);
}
.fresh__dot {
  width: 10px;
  height: 10px;
  margin-top: 5px;
  border-radius: 50%;
  background: var(--text-faint);
  flex: none;
}
.fresh--ok .fresh__dot { background: var(--ok); }
.fresh--warn .fresh__dot { background: var(--warn); }
.fresh--bad .fresh__dot { background: var(--up); }
.fresh__main { flex: 1; min-width: 0; }
.fresh__label { font-size: var(--fs-md); font-weight: 600; }
.fresh--ok .fresh__label { color: var(--ok); }
.fresh--warn .fresh__label { color: var(--warn); }
.fresh--bad .fresh__label { color: var(--up); }
.fresh__desc { margin-top: 3px; font-size: var(--fs-sm); color: var(--text-sub); }
.fresh__progress { margin-top: var(--sp-2); font-size: var(--fs-sm); color: var(--gold); }
.fresh__hint { margin: 0; padding: 0 var(--sp-5) var(--sp-4); font-size: var(--fs-xs); color: var(--text-faint); }
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
