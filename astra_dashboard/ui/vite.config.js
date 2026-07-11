import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const backendTarget = process.env.ASTRA_VITE_API_TARGET || process.env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8000'
const allowedHosts = String(process.env.ASTRA_VITE_ALLOWED_HOSTS || process.env.VITE_ALLOWED_HOSTS || '')
  .split(',')
  .map((host) => host.trim())
  .filter(Boolean)

export default defineConfig({
  plugins: [react()],
  root: '.',
  resolve: { alias: { '@': '/src' } },
  server: {
    host: process.env.ASTRA_FRONTEND_HOST || '0.0.0.0',
    port: Number(process.env.ASTRA_FRONTEND_PORT || 5173),
    allowedHosts,
    open: true,
    strictPort: true,
    cors: true,
    proxy: {
      '/api': {
        target: backendTarget,
        changeOrigin: false,
        ws: true,
      },
    },
    hmr: {
      protocol: 'ws',
      clientPort: Number(process.env.ASTRA_FRONTEND_PORT || 5173),
    },
    watch: { usePolling: true }
  }
})
