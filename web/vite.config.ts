import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig, loadEnv, type Plugin } from 'vite'

// /api/* -> control plane (prefix stripped). API_TARGET=http://localhost:8001 for the mock.
const target = process.env.API_TARGET ?? 'http://localhost:8000'
const proxy = { '/api': { target, changeOrigin: true, rewrite: (p: string) => p.replace(/^\/api/, '') } }

// Public, indexable routes. Case pages are per-visitor and stay out of the sitemap.
const ROUTES = ['/', '/console']

/** robots.txt and sitemap.xml from VITE_SITE_URL: served in dev, emitted on build. */
function seo(site: string): Plugin {
  const robots = `User-agent: *\nAllow: /\nDisallow: /cases/\n\nSitemap: ${site}/sitemap.xml\n`
  const sitemap = `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${
    ROUTES.map((r) => `  <url><loc>${site}${r}</loc></url>`).join('\n')}\n</urlset>\n`
  const files: Record<string, [string, string]> = { 'robots.txt': [robots, 'text/plain'], 'sitemap.xml': [sitemap, 'application/xml'] }
  return {
    name: 'bd-seo',
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const f = files[(req.url ?? '').replace(/^\//, '')]
        if (!f) return next()
        res.setHeader('content-type', f[1])
        res.end(f[0])
      })
    },
    generateBundle() {
      for (const [fileName, [source]] of Object.entries(files)) this.emitFile({ type: 'asset', fileName, source })
    },
  }
}

export default defineConfig(({ mode }) => {
  const site = (process.env.VITE_SITE_URL ?? loadEnv(mode, process.cwd(), 'VITE_').VITE_SITE_URL ?? 'http://localhost:5173').replace(/\/$/, '')
  return {
    plugins: [react(), tailwindcss(), seo(site)],
    server: { port: Number(process.env.WEB_PORT ?? 5173), proxy },
    preview: { port: Number(process.env.WEB_PORT ?? 4173), proxy },
  }
})
