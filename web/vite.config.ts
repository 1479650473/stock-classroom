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
        // 可用环境变量指向别的后端端口：SC_API_TARGET=http://127.0.0.1:5001
        // （桌面版常驻 5000 时，开发环境可以换个端口，互不干扰）
        target: process.env.SC_API_TARGET || 'http://127.0.0.1:5000',
        changeOrigin: true,
      },
    },
    // 忽略 Tauri 的 target/ 目录, 避免 watch 到被锁定的 .exe 产物导致 EBUSY 崩溃。
    // 2026-10-15 追加：不少编辑器/工具用「写临时文件再改名」做原子保存，临时目录形如
    // `.tokens.css.<pid>.<uuid>.tmpdir/`。chokidar 会抓到其中的文件并抛
    // EBUSY(resource busy or locked)；该异常是 FSWatcher 的 error 事件，
    // **未捕获会直接杀掉 vite 进程** —— 实测发生过：dev server 静默退出，
    // 页面变成 ERR_CONNECTION_REFUSED，而日志里只有一段堆栈。
    // 因此把所有临时产物模式一律排除。
    watch: {
      ignored: [
        '**/src-tauri/target/**',
        '**/src-tauri/**',
        '**/dist/**',
        '**/node_modules/**',
        '**/*.tmpdir/**',
        '**/*.tmp',
        '**/.*.tmp',
      ],
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
