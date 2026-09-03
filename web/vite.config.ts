import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

// Dev: proxy /api to the Flask backend on 127.0.0.1:5000 so the SPA can be
// developed with hot reload without CORS pain. Production (Tauri) calls the
// absolute backend URL from the client.
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:5000',
        changeOrigin: true,
      },
    },
    // 忽略 Tauri 的 target/ 目录, 避免 watch 到被锁定的 .exe 产物导致 EBUSY 崩溃
    watch: {
      ignored: ['**/src-tauri/target/**', '**/src-tauri/**', '**/dist/**', '**/node_modules/**'],
    },
  },
  build: {
    outDir: 'dist',
    target: 'es2020',
    chunkSizeWarningLimit: 1500,
    rollupOptions: {
      output: {
        manualChunks: {
          echarts: ['echarts'],
          vendor: ['vue', 'vue-router', 'pinia'],
        },
      },
    },
  },
})
