import { defineStore } from 'pinia'
import { getBootstrap, getSettings, saveSettings } from '@/api'
import { appReady, isTauri } from '@/lib/tauri'
import type { Bootstrap } from '@/api'

export type ThemeKey = 'graphite' | 'obsidian' | 'ivory'

export const useAppStore = defineStore('app', {
  state: () => ({
    theme: (localStorage.getItem('sc_theme') as ThemeKey) || 'graphite',
    fontSize: Number(localStorage.getItem('sc_font')) || 14,
    bootstrap: null as Bootstrap | null,
    aiConfigured: false,
    ready: false,
    backendOnline: true,
  }),
  actions: {
    applyTheme() {
      document.documentElement.setAttribute('data-theme', this.theme)
      document.documentElement.style.fontSize = this.fontSize + 'px'
    },
    setTheme(t: ThemeKey, persist = true) {
      this.theme = t
      localStorage.setItem('sc_theme', t)
      this.applyTheme()
      if (persist) saveSettings({ theme: t }).catch(() => {})
    },
    setFontSize(px: number, persist = true) {
      this.fontSize = px
      localStorage.setItem('sc_font', String(px))
      this.applyTheme()
      if (persist) saveSettings({ font_size: px }).catch(() => {})
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

    async init() {
      this.applyTheme()
      try {
        const s = await getSettings()
        const theme = (s.theme as ThemeKey) || this.theme
        this.theme = theme
        this.applyTheme()
      } catch {
        /* backend offline — keep local */
      }
      // 桌面端：主窗口先不出现，等本地服务真正可用再显示（避免"打开了但一片离线"）
      if (isTauri()) {
        await this.waitBackend()
      } else {
        try {
          const b = await getBootstrap()
          this.bootstrap = b
          this.aiConfigured = b.ai_configured
          this.backendOnline = true
        } catch {
          this.backendOnline = false
        }
      }
      this.ready = true
      // 桌面外壳：前端就绪 → 关掉启动闪屏、显示主窗口（浏览器里是 no-op）
      void appReady()
      // 首屏渲染完之后，趁空闲把其它主页面「预热」：JS chunk + 关键接口的缓存
      void this.prefetch()
    },
  },
})
