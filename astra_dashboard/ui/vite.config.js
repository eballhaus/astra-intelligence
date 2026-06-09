import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  root: '.',
  resolve: { alias: { '@': '/src' } },
  server: {
    host: '0.0.0.0',
    port: 5173,
    allowedHosts: true,
    open: true,
    strictPort: true,
    cors: true,
    hmr: {
      protocol: 'ws',
      clientPort: 5173,
    },
    watch: { usePolling: true }
  }
})
