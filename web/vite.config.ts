import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

// /api/* -> control plane (prefix stripped). API_TARGET=http://localhost:8001 for the mock.
const target = process.env.API_TARGET ?? 'http://localhost:8000'
const proxy = { '/api': { target, changeOrigin: true, rewrite: (p: string) => p.replace(/^\/api/, '') } }

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { port: Number(process.env.WEB_PORT ?? 5173), proxy },
  preview: { port: Number(process.env.WEB_PORT ?? 4173), proxy },
})
