import { defineStore } from 'pinia'
import { getBootstrap, getSettings, saveSettings } from '@/api'
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
      try {
        const b = await getBootstrap()
        this.bootstrap = b
        this.aiConfigured = b.ai_configured
        this.backendOnline = true
      } catch {
        this.backendOnline = false
      }
      this.ready = true
    },
  },
})
