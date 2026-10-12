import { fileURLToPath, URL } from 'node:url'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const backend = process.env.VSA_BACKEND_URL ?? 'http://127.0.0.1:8775'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    // /open cambia el token de sesión por la cookie (ver backend/app/session.py).
    proxy: { '/api': { target: backend, changeOrigin: false }, '/open': { target: backend, changeOrigin: false } },
  },
  build: {
    target: 'es2023',
    chunkSizeWarningLimit: 900,
  },
})
