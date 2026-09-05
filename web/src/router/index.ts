import { createRouter, createWebHashHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'

// explicit import map (Vite needs statically-analyzable paths)
const viewModules: Record<string, () => Promise<{ default: unknown }>> = {
  overview: () => import('@/views/Overview.vue'),
  market: () => import('@/views/Market.vue'),
  research: () => import('@/views/Research.vue'),
  picks: () => import('@/views/Picks.vue'),
  trade: () => import('@/views/Trade.vue'),
  holdings: () => import('@/views/Holdings.vue'),
  agentops: () => import('@/views/AgentOps.vue'),
  agent: () => import('@/views/Agent.vue'),
  optimize: () => import('@/views/Optimize.vue'),
  kline: () => import('@/views/Kline.vue'),
  datacenter: () => import('@/views/DataCenter.vue'),
  pipeline: () => import('@/views/Pipeline.vue'),
  trainer: () => import('@/views/Trainer.vue'),
  flow: () => import('@/views/Flow.vue'),
  replay: () => import('@/views/Replay.vue'),
}

const ALL_ROUTES: RouteRecordRaw[] = [
  { path: '/', redirect: '/overview' },
  { path: '/overview', name: 'overview', component: viewModules.overview, meta: { title: '总览' } },
  { path: '/market', name: 'market', component: viewModules.market, meta: { title: '看盘' } },
  { path: '/research', name: 'research', component: viewModules.research, meta: { title: '研究' } },
  { path: '/picks', name: 'picks', component: viewModules.picks, meta: { title: '选股' } },
  { path: '/trade', name: 'trade', component: viewModules.trade, meta: { title: '交易' } },
  { path: '/holdings', name: 'holdings', component: viewModules.holdings, meta: { title: '持仓' } },
  { path: '/agentops', name: 'agentops', component: viewModules.agentops, meta: { title: 'AI操盘' } },
  { path: '/agent', name: 'agent', component: viewModules.agent, meta: { title: 'AI操盘台' } },
  { path: '/optimize', name: 'optimize', component: viewModules.optimize, meta: { title: '策略进化' } },
  { path: '/kline', name: 'kline', component: viewModules.kline, meta: { title: 'K线' } },
  { path: '/datacenter', name: 'datacenter', component: viewModules.datacenter, meta: { title: '数据中心' } },
  { path: '/pipeline', name: 'pipeline', component: viewModules.pipeline, meta: { title: '数据管道' } },
  { path: '/trainer', name: 'trainer', component: viewModules.trainer, meta: { title: '训练' } },
  { path: '/flow', name: 'flow', component: viewModules.flow, meta: { title: '指挥舱' } },
  { path: '/replay', name: 'replay', component: viewModules.replay, meta: { title: '策略回放' } },
  { path: '/settings', name: 'settings', component: () => import('@/views/Settings.vue'), meta: { title: '设置' } },
  { path: '/:pathMatch(.*)*', redirect: '/overview' },
]

const router = createRouter({
  history: createWebHashHistory(),
  routes: ALL_ROUTES,
})

router.afterEach((to) => {
  document.title = to.meta?.title ? `${to.meta.title} · 股票教室` : '股票教室'
})

export default router
