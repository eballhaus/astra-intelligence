import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  root: '.',
  resolve: { alias: { '@': '/src' } },
  server: {
    host: '0.0.0.0',
    allowedHosts: [
      'erics-mac-mini.tailb8a048.ts.net',
      'localhost',
      '127.0.0.1'
    ],
    port: 5173,
    open: true,
    strictPort: true,
    cors: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true
      }
    },
    watch: { usePolling: true }
  }
})
