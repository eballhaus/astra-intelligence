import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  root: '.',
  resolve: { alias: { '@': '/src' } },
  server: {
    host: '0.0.0.0',
    port: 5173,
    allowedHosts: ['.ts.net', 'localhost', '127.0.0.1', 'erics-mac-mini.tailb8a048.ts.net'],
    open: true,
    strictPort: true,
    cors: true,
    watch: { usePolling: true }
  }
})
