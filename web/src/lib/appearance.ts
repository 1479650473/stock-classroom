/**
 * 主题与外观注册表 —— 单一声明源。
 *
 * 设计约定（2026-10-15）：
 * 1. 主题 = 一组 CSS 变量，写在 `styles/tokens.css` 的 `:root[data-theme='<key>']` 块里。
 *    本文件只登记「有哪些主题、怎么展示」，**不重复定义颜色**，避免两处漂移。
 * 2. 外观维度（密度/圆角/动效/背景纹理）是**与主题正交**的：
 *    通过 `<html>` 上的 `data-*` 属性切换，样式在 `styles/appearance.css` 里收口。
 *    这样「换主题」不会重置「紧凑度」，反之亦然。
 * 3. 所有取值都持久化到 localStorage + 后端 settings（见 stores/app.ts）。
 */

export type ThemeKey =
  | 'graphite'
  | 'obsidian'
  | 'ivory'
  | 'midnight'
  | 'nord'
  | 'sepia'
  | 'sakura'
  | 'contrast'

export type ThemeFamily = 'dark' | 'light'

export interface ThemeDef {
  key: ThemeKey
  label: string
  /** 一句话定位，显示在设置页 */
  hint: string
  family: ThemeFamily
  /** 色板预览：4 个色块（背景/面板/强调/强调副色） */
  swatch: [string, string, string, string]
}

/** 主题清单：顺序即设置页展示顺序（深色在前，浅色在后）。 */
export const THEMES: ThemeDef[] = [
  {
    key: 'graphite',
    label: '石墨',
    hint: '中性深灰 · 蓝色强调（默认）',
    family: 'dark',
    swatch: ['#0b0d11', '#14171c', '#7aa2f7', '#b48ead'],
  },
  {
    key: 'obsidian',
    label: '黑曜',
    hint: '纯黑底 · 琥珀金强调',
    family: 'dark',
    swatch: ['#060708', '#0e1012', '#e0a050', '#c9a0dc'],
  },
  {
    key: 'midnight',
    label: '午夜蓝',
    hint: '深藏蓝 · 青蓝强调',
    family: 'dark',
    swatch: ['#0a1020', '#131c2e', '#4fc3f7', '#7c9cff'],
  },
  {
    key: 'nord',
    label: '北境',
    hint: '冷调石板 · 雾蓝强调',
    family: 'dark',
    swatch: ['#2e3440', '#3b4252', '#88c0d0', '#b48ead'],
  },
  {
    key: 'contrast',
    label: '高对比',
    hint: '纯黑纯白 · 最大可读性（视力/投屏友好）',
    family: 'dark',
    swatch: ['#000000', '#0f0f0f', '#ffe14d', '#66d9ff'],
  },
  {
    key: 'ivory',
    label: '象牙',
    hint: '暖白纸感 · 朱红强调（默认浅色）',
    family: 'light',
    swatch: ['#f3eee6', '#fbf8f2', '#8e3a2f', '#a9812e'],
  },
  {
    key: 'sepia',
    label: '羊皮纸',
    hint: '复古黄褐 · 墨棕强调',
    family: 'light',
    swatch: ['#ece0c8', '#f6eeda', '#6b4a2f', '#8a6a3a'],
  },
  {
    key: 'sakura',
    label: '樱雪',
    hint: '浅粉冷白 · 莓红强调',
    family: 'light',
    swatch: ['#f7eef1', '#fdf7f9', '#b52d5a', '#8a5aa8'],
  },
]

export const THEME_MAP: Record<string, ThemeDef> = Object.fromEntries(
  THEMES.map((t) => [t.key, t]),
)

export function isThemeKey(v: unknown): v is ThemeKey {
  return typeof v === 'string' && v in THEME_MAP
}

/* ------------------------------------------------------------------ */
/* 外观维度                                                            */
/* ------------------------------------------------------------------ */

export type Density = 'comfortable' | 'compact' | 'roomy'
export type Radius = 'sharp' | 'default' | 'round'
export type Motion = 'full' | 'reduced'
export type Backdrop = 'grid' | 'plain' | 'none'

export interface AppearanceOption<T extends string> {
  key: T
  label: string
  hint: string
}

export const DENSITIES: AppearanceOption<Density>[] = [
  { key: 'compact', label: '紧凑', hint: '行高与间距更小，同屏信息更多' },
  { key: 'comfortable', label: '标准', hint: '默认间距' },
  { key: 'roomy', label: '宽松', hint: '更疏朗，适合大屏' },
]

export const RADII: AppearanceOption<Radius>[] = [
  { key: 'sharp', label: '直角', hint: '硬朗，表格类界面更整齐' },
  { key: 'default', label: '标准', hint: '默认圆角' },
  { key: 'round', label: '圆润', hint: '更柔和的观感' },
]

export const MOTIONS: AppearanceOption<Motion>[] = [
  { key: 'full', label: '完整', hint: '保留过渡与动画' },
  { key: 'reduced', label: '精简', hint: '几乎无动画，适合远程桌面/低配机' },
]

export const BACKDROPS: AppearanceOption<Backdrop>[] = [
  { key: 'grid', label: '网格', hint: '顶部极淡网格+光晕（默认，有纵深）' },
  { key: 'plain', label: '纯色', hint: '只留顶部光晕，不要网格' },
  { key: 'none', label: '无', hint: '完全纯色背景，最省性能' },
]

export const FONT_SIZE_OPTIONS = [12, 13, 14, 15, 16, 17] as const
export type FontSize = (typeof FONT_SIZE_OPTIONS)[number]
