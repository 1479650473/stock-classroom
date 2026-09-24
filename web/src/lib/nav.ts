// Single source of truth for the left navigation (v6).
// 6 个主页面 + 设置（设置入口在顶栏右侧，不进主导航）。
export interface NavItem {
  path: string
  name: string
  title: string
  icon: string
  /** 一句话说明，用于 hover 提示 */
  hint?: string
}

export interface NavGroup {
  label: string
  items: NavItem[]
}

export const NAV: NavGroup[] = [
  {
    label: '',
    items: [
      { path: '/', name: 'dashboard', title: '工作台', icon: 'overview', hint: '账户 · 关注 · 快捷操作' },
      { path: '/market', name: 'market', title: '行情', icon: 'market', hint: '市场全景 · 个股K线' },
      { path: '/strategy', name: 'strategy', title: '策略', icon: 'research', hint: '环境 · 回测 · 进化 · 回放' },
      { path: '/trade', name: 'trade', title: '交易', icon: 'trade', hint: '三体系总览 · 模拟盘 · 持仓/下单/选股' },
      { path: '/ai', name: 'ai', title: 'AI', icon: 'chat', hint: 'AI 操盘手 · 对话操盘 · 工具台' },
      { path: '/data', name: 'data', title: '数据', icon: 'database', hint: '数据管道 · 数据库 · 训练' },
    ],
  },
]

export const ALL_ROUTES: NavItem[] = NAV.flatMap((g) => g.items)
