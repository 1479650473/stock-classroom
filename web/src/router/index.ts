import { createRouter, createWebHashHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'

// explicit import map (Vite needs statically-analyzable paths)
const viewModules: Record<string, () => Promise<{ default: unknown }>> = {
  dashboard: () => import('@/views/v6/Dashboard.vue'),
  market: () => import('@/views/v6/Market.vue'),
  strategy: () => import('@/views/v6/Strategy.vue'),
  // 「实盘」已并入「交易」页的页内 tab，不再是一级路由（旧 /live 保留为重定向）
  trade: () => import('@/views/v6/Trade.vue'),
  ai: () => import('@/views/v6/AI.vue'),
  data: () => import('@/views/v6/Data.vue'),
  settings: () => import('@/views/Settings.vue'),
}

const ALL_ROUTES: RouteRecordRaw[] = [
  { path: '/', name: 'dashboard', component: viewModules.dashboard, meta: { title: '工作台' } },
  { path: '/market', name: 'market', component: viewModules.market, meta: { title: '行情' } },
  { path: '/strategy', name: 'strategy', component: viewModules.strategy, meta: { title: '策略' } },
  { path: '/trade', name: 'trade', component: viewModules.trade, meta: { title: '交易' } },
  { path: '/ai', name: 'ai', component: viewModules.ai, meta: { title: 'AI' } },
  { path: '/data', name: 'data', component: viewModules.data, meta: { title: '数据' } },

  { path: '/settings', name: 'settings', component: viewModules.settings, meta: { title: '设置' } },

  // ---- 旧路由兼容重定向（书签/习惯不失效） ----
  { path: '/sim', redirect: () => ({ path: '/trade', query: { tab: 'sim' } }) },
  // 「实盘」已并入「交易」的页内 tab
  { path: '/live', redirect: () => ({ path: '/trade', query: { tab: 'live' } }) },
  { path: '/realtime', redirect: () => ({ path: '/trade', query: { tab: 'live' } }) },
  // 被移除的三个模拟账户操作 tab：其信息现在在「模拟盘」（持仓明细 + 交易流水）
  { path: '/orders', redirect: () => ({ path: '/trade', query: { tab: 'sim' } }) },
  { path: '/order', redirect: () => ({ path: '/trade', query: { tab: 'sim' } }) },
  { path: '/overview', redirect: () => ({ path: '/' }) },
  { path: '/flow', redirect: () => ({ path: '/' }) },
  { path: '/kline', redirect: () => ({ path: '/market', query: { tab: 'stock' } }) },
  // 「套利」已降级为「行情」的页内分支：旧书签/侧边导航习惯不失效
  { path: '/arb', redirect: () => ({ path: '/market', query: { tab: 'arb' } }) },
  { path: '/picks', redirect: () => ({ path: '/trade', query: { tab: 'picks' } }) },
  // 旧「持仓」入口 → 模拟盘（持仓明细在那里）
  { path: '/holdings', redirect: () => ({ path: '/trade', query: { tab: 'sim' } }) },
  // AI 页内标签 2026-10-16 改名为 操盘台/工具台；旧 URL 语义一致，值保留兼容
  { path: '/agentops', redirect: () => ({ path: '/ai', query: { tab: 'tools' } }) },
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
