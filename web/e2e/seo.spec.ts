import { expect, test } from '@playwright/test'
import { execSync } from 'node:child_process'
import { readFileSync } from 'node:fs'

const SITE = process.env.VITE_SITE_URL ?? 'http://localhost:5173'

test('/ carries title, description, Open Graph, Twitter card and canonical', async ({ page }) => {
  await page.goto('/')
  await expect(page).toHaveTitle(/\S/)
  const meta = (sel: string) => page.locator(sel).first().getAttribute('content')
  expect(await meta('meta[name="description"]')).toBeTruthy()
  expect(await meta('meta[property="og:title"]')).toBeTruthy()
  expect(await meta('meta[property="og:description"]')).toBeTruthy()
  expect(await meta('meta[property="og:image"]')).toMatch(new RegExp(`^${SITE.replace(/[.:/]/g, '\\$&')}/`))
  expect(await meta('meta[name="twitter:card"]')).toBe('summary_large_image')
  expect(await page.locator('link[rel="canonical"]').first().getAttribute('href')).toBe(`${SITE}/`)
})

test('robots.txt is served and points at the sitemap', async ({ request }) => {
  const r = await request.get('/robots.txt')
  expect(r.status()).toBe(200)
  expect(await r.text()).toContain(`Sitemap: ${SITE}/sitemap.xml`)
})

test('the build writes a sitemap listing / and /console under VITE_SITE_URL', () => {
  test.setTimeout(120_000)
  execSync('npx vite build --outDir dist-seo --emptyOutDir', { stdio: 'pipe', env: { ...process.env, VITE_SITE_URL: SITE } })
  const xml = readFileSync('dist-seo/sitemap.xml', 'utf8')
  expect(xml).toContain(`<loc>${SITE}/</loc>`)
  expect(xml).toContain(`<loc>${SITE}/console</loc>`)
  expect(readFileSync('dist-seo/robots.txt', 'utf8')).toContain(`${SITE}/sitemap.xml`)
})

test('an unknown path renders the 404 page with its own title', async ({ page }) => {
  await page.goto('/no/such/page')
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(/not found|Nothing/i)
  await expect(page).toHaveTitle(/not found/i)
})
