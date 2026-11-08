// probe: how does Playwright record video at dsf 2? (resolution + start alignment)
import pw from 'file:///C:/dev/wt-video/web/node_modules/playwright/index.mjs'

const browser = await pw.chromium.launch()
const ctx = await browser.newContext({
  viewport: { width: 1920, height: 1080 },
  deviceScaleFactor: 2,
  recordVideo: { dir: 'C:/dev/wt-video/video/capture/raw', size: { width: 3840, height: 2160 } },
})
await ctx.addInitScript(() => localStorage.setItem('bd.operator', 'demo'))
const t0 = Date.now()
const page = await ctx.newPage()
page.on('pageerror', (e) => console.log('pageerror:', e.message))
page.on('console', (m) => m.type() === 'error' && console.log('console:', m.text()))
await page.goto('http://localhost:4173/console')
await page.waitForSelector('[data-testid="server-inst-shop-prod"]', { timeout: 15000 })
console.log('rows visible at', Date.now() - t0, 'ms')
await page.waitForTimeout(2500)
const video = page.video()
await ctx.close()
console.log('video:', await video.path())
await browser.close()
