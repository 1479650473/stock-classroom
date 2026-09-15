/**
 * 图表主题：从设计令牌（CSS 变量）派生图表用色，保证 K 线 / ECharts 与页面同色系，
 * 且三主题（graphite / obsidian / ivory）切换时自动跟随。
 *
 * 用法：
 *   import { chartTokens, maColors, ensureEChartsTheme } from '@/lib/chartTheme'
 *   const t = chartTokens()               // 取当前主题下的图表色
 *   echarts.init(el, ensureEChartsTheme()) // 用统一主题初始化
 */
import * as echarts from 'echarts'

export interface ChartTokens {
  text: string
  textSub: string
  textFaint: string
  border: string
  borderSoft: string
  panel: string
  glass: string
  up: string
  down: string
  gold: string
  accent: string
  info: string
  warn: string
  fontUi: string
  fontNum: string
}

function v(name: string, fallback: string): string {
  const raw = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return raw || fallback
}

/** 当前主题下的图表用色（每次调用都重新解析，主题切换后即时生效） */
export function chartTokens(): ChartTokens {
  return {
    text: v('--text', '#E8EAED'),
    textSub: v('--text-sub', '#9AA3B0'),
    textFaint: v('--text-faint', '#5C6670'),
    border: v('--border', '#232830'),
    borderSoft: v('--border-soft', '#1D222A'),
    panel: v('--bg-panel', '#14171C'),
    glass: v('--glass', 'rgba(20,23,28,0.72)'),
    up: v('--up', '#E5484D'),      // A股：涨=红
    down: v('--down', '#3FB950'),  // 跌=绿
    gold: v('--gold', '#D4A574'),
    accent: v('--accent', '#7AA2F7'),
    info: v('--info', '#7AA2F7'),
    warn: v('--warn', '#D29922'),
    fontUi: v('--font-sans', 'system-ui, sans-serif'),
    fontNum: v('--font-num', 'monospace'),
  }
}

/** 均线配色：与主题同一族（金/蓝/青/橙），避免高饱和杂色 */
export function maColors(): string[] {
  const t = chartTokens()
  return [t.gold, t.accent, t.info, t.warn, t.textSub]
}

/** ECharts tooltip 统一外观 */
export function tooltipStyle() {
  const t = chartTokens()
  return {
    backgroundColor: `color-mix(in srgb, var(--bg-overlay) 92%, transparent)`,
    borderColor: t.border,
    borderWidth: 1,
    padding: [8, 10] as [number, number],
    textStyle: { color: t.text, fontSize: 12, fontFamily: t.fontNum },
    extraCssText: 'backdrop-filter: blur(8px); border-radius: 8px; box-shadow: 0 8px 24px rgba(0,0,0,.28);',
    axisPointer: {
      lineStyle: { color: t.gold, opacity: 0.55, type: 'dashed' as const },
      crossStyle: { color: t.gold, opacity: 0.5 },
      label: { backgroundColor: t.panel, borderColor: t.border, borderWidth: 1, color: t.text },
    },
  }
}

const THEME_NAME = 'sc-tokens'
let registered = ''

/**
 * 注册（或刷新）名为 sc-tokens 的 ECharts 主题，返回主题名。
 * 每次主题切换后调用一次，再 echarts.init(el, name) 即可拿到正确的轴/文字/提示色。
 */
export function ensureEChartsTheme(force = false): string {
  const t = chartTokens()
  const stamp = `${t.text}|${t.border}|${t.gold}`
  if (!force && registered === stamp) return THEME_NAME
  registered = stamp

  echarts.registerTheme(THEME_NAME, {
    color: [t.gold, t.accent, t.info, t.warn, t.textSub, t.down],
    backgroundColor: 'transparent',
    textStyle: { fontFamily: t.fontUi, fontSize: 12, color: t.textSub },
    title: {
      textStyle: { color: t.text, fontSize: 13, fontWeight: 600 },
      subtextStyle: { color: t.textFaint, fontSize: 11 },
    },
    legend: {
      textStyle: { color: t.textSub, fontSize: 11 },
      inactiveColor: t.textFaint,
      itemWidth: 10,
      itemHeight: 8,
    },
    grid: { left: 8, right: 12, top: 24, bottom: 8, containLabel: true },
    tooltip: {
      backgroundColor: 'rgba(20,23,28,0.92)',
      borderColor: t.border,
      borderWidth: 1,
      padding: [8, 10],
      textStyle: { color: t.text, fontSize: 12 },
      extraCssText: 'backdrop-filter: blur(8px); border-radius: 8px;',
      axisPointer: { lineStyle: { color: t.gold, opacity: 0.5 } },
    },
    categoryAxis: {
      axisLine: { lineStyle: { color: t.border } },
      axisTick: { show: false },
      axisLabel: { color: t.textFaint, fontSize: 11 },
      splitLine: { show: false },
    },
    valueAxis: {
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: t.textFaint, fontSize: 11 },
      splitLine: { lineStyle: { color: t.borderSoft, type: 'dashed' } },
    },
    timeAxis: {
      axisLine: { lineStyle: { color: t.border } },
      axisTick: { show: false },
      axisLabel: { color: t.textFaint, fontSize: 11, hideOverlap: true },
      splitLine: { show: false },
    },
    line: { symbol: 'none', smooth: false, lineStyle: { width: 1.6 } },
    bar: { itemStyle: { borderRadius: [2, 2, 0, 0] } },
  } as never)

  return THEME_NAME
}

/** tooltip 的 HTML 内联配色（老图表手写 formatter 时用） */
export function tooltipInline(): { label: string; up: string; down: string; dim: string } {
  const t = chartTokens()
  return { label: t.textSub, up: t.up, down: t.down, dim: t.textFaint }
}

/** 监听主题切换（MutationObserver 包装），返回取消函数 */
export function onThemeChange(cb: () => void): () => void {
  const mo = new MutationObserver(cb)
  mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
  return () => mo.disconnect()
}
