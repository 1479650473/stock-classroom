import { createRouter, createWebHashHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'

// explicit import map (Vite needs statically-analyzable paths)
const viewModules: Record<string, () => Promise<{ default: unknown }>> = {
  dashboard: () => import('@/views/v6/Dashboard.vue'),
  market: () => import('@/views/v6/Market.vue'),
  strategy: () => import('@/views/v6/Strategy.vue'),
  trade: () => import('@/views/v6/Trade.vue'),
  live: () => import('@/views/v6/Live.vue'),
  ai: () => import('@/views/v6/AI.vue'),
  data: () => import('@/views/v6/Data.vue'),
  settings: () => import('@/views/Settings.vue'),
}

const ALL_ROUTES: RouteRecordRaw[] = [
  { path: '/', name: 'dashboard', component: viewModules.dashboard, meta: { title: '工作台' } },
  { path: '/market', name: 'market', component: viewModules.market, meta: { title: '行情' } },
  { path: '/strategy', name: 'strategy', component: viewModules.strategy, meta: { title: '策略' } },
  { path: '/trade', name: 'trade', component: viewModules.trade, meta: { title: '交易' } },
  { path: '/live', name: 'live', component: viewModules.live, meta: { title: '实盘' } },
  { path: '/ai', name: 'ai', component: viewModules.ai, meta: { title: 'AI' } },
  { path: '/data', name: 'data', component: viewModules.data, meta: { title: '数据' } },

  { path: '/settings', name: 'settings', component: viewModules.settings, meta: { title: '设置' } },

  // ---- 旧路由兼容重定向（书签/习惯不失效） ----
  { path: '/sim', redirect: () => ({ path: '/trade', query: { tab: 'sim' } }) },
  { path: '/realtime', redirect: () => ({ path: '/live' }) },
  { path: '/overview', redirect: () => ({ path: '/' }) },
  { path: '/flow', redirect: () => ({ path: '/' }) },
  { path: '/kline', redirect: () => ({ path: '/market', query: { tab: 'stock' } }) },
  // 「套利」已降级为「行情」的页内分支：旧书签/侧边导航习惯不失效
  { path: '/arb', redirect: () => ({ path: '/market', query: { tab: 'arb' } }) },
  { path: '/picks', redirect: () => ({ path: '/trade', query: { tab: 'picks' } }) },
  { path: '/holdings', redirect: () => ({ path: '/trade', query: { tab: 'positions' } }) },
  { path: '/agentops', redirect: () => ({ path: '/ai', query: { tab: 'auto' } }) },
  { path: '/agent', redirect: () => ({ path: '/ai', query: { tab: 'chat' } }) },
  { path: '/optimize', redirect: () => ({ path: '/strategy', query: { tab: 'optimize' } }) },
  { path: '/replay', redirect: () => ({ path: '/strategy', query: { tab: 'replay' } }) },
  { path: '/research', redirect: () => ({ path: '/strategy', query: { tab: 'research' } }) },
  { path: '/datacenter', redirect: () => ({ path: '/data', query: { tab: 'db' } }) },
  { path: '/pipeline', redirect: () => ({ path: '/data', query: { tab: 'pipeline' } }) },
  { path: '/trainer', redirect: () => ({ path: '/data', query: { tab: 'trainer' } }) },

  { path: '/:pathMatch(.*)*', redirect: () => ({ path: '/' }) },
]

const router = createRouter({
  history: createWebHashHistory(),
  routes: ALL_ROUTES,
})

router.afterEach((to) => {
  document.title = to.meta?.title ? `${to.meta.title} · 股票教室` : '股票教室'
})

export default router
