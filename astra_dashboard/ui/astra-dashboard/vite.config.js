// vite.config.js — Astra Dashboard (fixed root)
export default {
  root: '.',
  resolve: {
    alias: { '@': '/src' }
  },
  server: {
    port: 5173,
    open: true,
    strictPort: true,
    watch: { usePolling: true }
  }
};
