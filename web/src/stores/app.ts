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
    },
  },
})
