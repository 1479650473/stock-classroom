// Single source of truth for the left navigation (merged — no more dual
// nav rail + stepbar). Each item maps to a route.
export interface NavItem {
  path: string
  name: string
  title: string
  icon: string
}

export interface NavGroup {
  label: string
  items: NavItem[]
}

export const NAV: NavGroup[] = [
  {
    label: '工作流',
    items: [
      { path: '/overview', name: 'overview', title: '总览', icon: 'overview' },
      { path: '/market', name: 'market', title: '看盘', icon: 'market' },
      { path: '/research', name: 'research', title: '研究', icon: 'research' },
      { path: '/picks', name: 'picks', title: '选股', icon: 'picks' },
      { path: '/trade', name: 'trade', title: '交易', icon: 'trade' },
      { path: '/holdings', name: 'holdings', title: '持仓', icon: 'holdings' },
      { path: '/agentops', name: 'agentops', title: 'AI操盘', icon: 'agentops' },
      { path: '/agent', name: 'agent', title: 'AI操盘台', icon: 'chat' },
      { path: '/optimize', name: 'optimize', title: '策略进化', icon: 'trending' },
    ],
  },
  {
    label: '数据工具',
    items: [
      { path: '/kline', name: 'kline', title: 'K线', icon: 'kline' },
      { path: '/datacenter', name: 'datacenter', title: '数据中心', icon: 'datacenter' },
      { path: '/pipeline', name: 'pipeline', title: '数据管道', icon: 'pipeline' },
      { path: '/trainer', name: 'trainer', title: '训练', icon: 'trainer' },
      { path: '/flow', name: 'flow', title: '指挥舱', icon: 'flow' },
    ],
  },
]

export const ALL_ROUTES: NavItem[] = NAV.flatMap((g) => g.items)
