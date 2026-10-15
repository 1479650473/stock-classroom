import { defineStore } from 'pinia'
import { getBootstrap, getSettings, saveSettings } from '@/api'
import { appReady, isTauri } from '@/lib/tauri'
import {
  isThemeKey,
  type Backdrop,
  type Density,
  type FontSize,
  type Motion,
  type Radius,
  type ThemeKey,
} from '@/lib/appearance'
import type { Bootstrap } from '@/api'

/* localStorage 读取助手：类型不符或缺失时回落到默认值，
   避免旧版本残留的脏值把界面带到未知状态。 */
function ls<T extends string>(key: string, allow: readonly T[], fallback: T): T {
  const v = localStorage.getItem(key)
  return allow.includes(v as T) ? (v as T) : fallback
}
function lsNum(key: string, allow: readonly number[], fallback: number): number {
  const v = Number(localStorage.getItem(key))
  return allow.includes(v) ? v : fallback
}

const THEME_KEYS: ThemeKey[] = [
  'graphite', 'obsidian', 'ivory', 'midnight', 'nord', 'sepia', 'sakura', 'contrast',
]
const DENSITY_KEYS = ['comfortable', 'compact', 'roomy'] as const
const RADIUS_KEYS = ['sharp', 'default', 'round'] as const
const MOTION_KEYS = ['full', 'reduced'] as const
const BACKDROP_KEYS = ['grid', 'plain', 'none'] as const
const FONT_SIZES = [12, 13, 14, 15, 16, 17] as const

export const useAppStore = defineStore('app', {
  state: () => ({
    /* ---- 外观（主题 + 4 个正交维度）---- */
    theme: ls<ThemeKey>('sc_theme', THEME_KEYS, 'graphite'),
    fontSize: lsNum('sc_font', FONT_SIZES, 14) as FontSize,
    density: ls<Density>('sc_density', DENSITY_KEYS, 'comfortable'),
    radius: ls<Radius>('sc_radius', RADIUS_KEYS, 'default'),
    motion: ls<Motion>('sc_motion', MOTION_KEYS, 'full'),
    backdrop: ls<Backdrop>('sc_backdrop', BACKDROP_KEYS, 'grid'),

    bootstrap: null as Bootstrap | null,
    aiConfigured: false,
    ready: false,
    backendOnline: true,
  }),
  actions: {
    /** 把全部外观维度写到 <html> 上。CSS 层订阅这些 data-* 属性。 */
    applyTheme() {
      const el = document.documentElement
      el.setAttribute('data-theme', this.theme)
      el.setAttribute('data-density', this.density)
      el.setAttribute('data-radius', this.radius)
      el.setAttribute('data-motion', this.motion)
      el.setAttribute('data-backdrop', this.backdrop)
      el.style.fontSize = this.fontSize + 'px'
    },

    /** 一次性持久化全部外观项（localStorage 立即生效 + 后端异步保存） */
    _persistAppearance() {
      localStorage.setItem('sc_theme', this.theme)
      localStorage.setItem('sc_font', String(this.fontSize))
      localStorage.setItem('sc_density', this.density)
      localStorage.setItem('sc_radius', this.radius)
      localStorage.setItem('sc_motion', this.motion)
      localStorage.setItem('sc_backdrop', this.backdrop)
      saveSettings({
        theme: this.theme,
        font_size: this.fontSize,
        density: this.density,
        radius: this.radius,
        motion: this.motion,
        backdrop: this.backdrop,
      }).catch(() => {})
    },

    setTheme(t: ThemeKey, persist = true) {
      this.theme = t
      this.applyTheme()
      if (persist) this._persistAppearance()
    },
    setFontSize(px: FontSize | number, persist = true) {
      this.fontSize = px as FontSize
      this.applyTheme()
      if (persist) this._persistAppearance()
    },
    setDensity(d: Density, persist = true) {
      this.density = d
      this.applyTheme()
      if (persist) this._persistAppearance()
    },
    setRadius(r: Radius, persist = true) {
      this.radius = r
      this.applyTheme()
      if (persist) this._persistAppearance()
    },
    setMotion(m: Motion, persist = true) {
      this.motion = m
      this.applyTheme()
      if (persist) this._persistAppearance()
    },
    setBackdrop(b: Backdrop, persist = true) {
      this.backdrop = b
      this.applyTheme()
      if (persist) this._persistAppearance()
    },
    /** 恢复出厂外观（只动外观，不动 AI/桌面等其它设置） */
    resetAppearance() {
      this.theme = 'graphite'
      this.fontSize = 14
      this.density = 'comfortable'
      this.radius = 'default'
      this.motion = 'full'
      this.backdrop = 'grid'
      this.applyTheme()
      this._persistAppearance()
    },

    /** 等后端就绪：桌面端启动时后端 sidecar 需要几秒（akshare 导入慢），期间停留在闪屏 */
    async waitBackend(timeoutMs = 25000): Promise<boolean> {
      const deadline = Date.now() + timeoutMs
      let delay = 250
      for (;;) {
        try {
          const b = await getBootstrap()
          this.bootstrap = b
          this.aiConfigured = b.ai_configured
          this.backendOnline = true
          return true
        } catch {
          this.backendOnline = false
        }
        if (Date.now() >= deadline) return false
        await new Promise((r) => setTimeout(r, delay))
        delay = Math.min(Math.round(delay * 1.4), 1200)
      }
    },

    /** 空闲预加载：把其它主页面的 chunk 与首屏接口预热，点进去就是现成的 */
    async prefetch() {
      const idle = (fn: () => void) =>
        (window.requestIdleCallback ? window.requestIdleCallback(fn, { timeout: 4000 }) : setTimeout(fn, 1200))
      idle(() => {
        // 1) 页面 chunk（动态 import 即预热，不挂载）
        for (const load of [
          () => import('@/views/v6/Market.vue'),
          () => import('@/views/v6/Trade.vue'),
          () => import('@/views/v6/Strategy.vue'),
          () => import('@/views/v6/Data.vue'),
          () => import('@/views/v6/AI.vue'),
        ]) {
          void load().catch(() => {})
        }
        // 2) 关键接口（顺序执行，避免启动瞬时并发；结果进 API 缓存）
        void (async () => {
          const { getIndices, getSectors, getOverview } = await import('@/api')
          for (const fn of [() => getOverview(), () => getIndices(), () => getSectors('industry')]) {
            try { await fn() } catch { /* 后端可能还没起来 */ }
          }
        })()
      })
    },

    /**
     * 启动初始化。
     *
     * 关键约束：**不要在这里 await 后端**。
     * `/api/system/bootstrap` 要扫 5GB 级 kline 库的 MAX(date)，冷启动实测 5.5s、
     * 热态约 940ms。以前 ready 等它，导致首屏白等一秒（桌面端有闪屏遮着，
     * Web 端就是白屏）。现在本地外观就绪即 ready，后端数据后台补。
     */
    init() {
      // ① 外观先落地：纯读 localStorage，同步完成 → 首帧就是用户选的主题，
      //    不会"先按默认主题画一帧、拿到 settings 后再跳变"。
      this.applyTheme()

      // ② 外壳立即可渲染。
      this.ready = true

      if (isTauri()) {
        // 桌面端例外：后端是随应用启动的 sidecar（akshare 导入慢）。
        // 主窗口本来就由 splash 挡着，等后端就绪再显示是对的 —— 露出空壳体验更差。
        void this.waitBackend()
      } else {
        // 浏览器：完全不阻塞渲染。
        void this.loadBackendState()
        void this.syncAppearanceFromBackend()
      }

      // 桌面外壳：前端就绪 → 关掉启动闪屏、显示主窗口（浏览器里是 no-op）
      void appReady()
      // 首屏渲染完之后，趁空闲把其它主页面「预热」：JS chunk + 关键接口的缓存
      void this.prefetch()
    },

    /** 后台补数据：bootstrap 含数据新鲜度，用于首屏各处提示。失败只标记离线，不阻塞。 */
    async loadBackendState() {
      // 兜底：万一后端半死不活（连得上但不应答），不要让 pending 永远悬着
      await Promise.race([
        (async () => {
          try {
            const b = await getBootstrap()
            this.bootstrap = b
            this.aiConfigured = b.ai_configured
            this.backendOnline = true
          } catch {
            this.backendOnline = false
          }
        })(),
        new Promise((r) => setTimeout(r, 12000)),
      ])
    },

    /** 后台同步外观：后端 settings 是权威（换机器/重装后仍保持偏好）。 */
    async syncAppearanceFromBackend() {
      try {
        const s = await getSettings()
        if (isThemeKey(s.theme)) this.theme = s.theme
        if (FONT_SIZES.includes(Number(s.font_size) as FontSize)) this.fontSize = Number(s.font_size) as FontSize
        if (DENSITY_KEYS.includes(s.density as Density)) this.density = s.density as Density
        if (RADIUS_KEYS.includes(s.radius as Radius)) this.radius = s.radius as Radius
        if (MOTION_KEYS.includes(s.motion as Motion)) this.motion = s.motion as Motion
        if (BACKDROP_KEYS.includes(s.backdrop as Backdrop)) this.backdrop = s.backdrop as Backdrop
        this.applyTheme()
      } catch {
        /* 离线：保留 localStorage 里的值 */
      }
    },
  },
})
