// D4 release evidence: seven required states at desktop and 390px.
// Usage: node scripts/shoot-d4.mjs <outDir> [baseUrl]
// Run against a production preview connected to the mock control plane.
import { chromium } from 'playwright'
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { createRequire } from 'node:module'

const [out = '.jury/d4', base = 'http://127.0.0.1:4400'] = process.argv.slice(2)
mkdirSync(out, { recursive: true })
const browser = await chromium.launch()
const axeSource = readFileSync(createRequire(import.meta.url).resolve('axe-core/axe.min.js'), 'utf8')
const report = { base, shots: [], overflow: {}, axe: {} }

const sizes = [
  { prefix: 'd', width: 1440, height: 900 },
  { prefix: 'm', width: 390, height: 844 },
]

async function capture(page, prefix, name, fullPage = false) {
  await page.waitForTimeout(350)
  const file = `${prefix}-${name}.png`
  await page.screenshot({ path: `${out}/${file}`, fullPage })
  report.shots.push(file)
  report.overflow[`${prefix}-${name}`] = await page.evaluate(() => ({
    viewport: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }))
  await page.addScriptTag({ content: axeSource })
  report.axe[`${prefix}-${name}`] = await page.evaluate(async () => (await window.axe.run()).violations.map((violation) => ({
    id: violation.id,
    impact: violation.impact,
    nodes: violation.nodes.length,
    targets: violation.nodes.map((node) => node.target),
    summary: violation.nodes.map((node) => node.failureSummary),
  })))
}

for (const size of sizes) {
  // A deterministic reduced-motion pass prevents scroll-reveal opacity tweens from
  // producing false transient contrast failures while axe samples each state.
  const context = await browser.newContext({ viewport: { width: size.width, height: size.height }, reducedMotion: 'reduce' })
  await context.request.post(`${base}/api/auth/session`, { data: { operator: 'qa' } })
  const page = await context.newPage()
  await page.addInitScript(() => localStorage.setItem('bd.operator', 'qa'))

  await page.goto(base)
  await page.waitForTimeout(1600)
  await capture(page, size.prefix, 'landing')

  await page.goto(`${base}/console`)
  await page.getByTestId('server-count').filter({ hasText: /\d/ }).waitFor()
  await capture(page, size.prefix, 'servers', true)

  await page.goto(base)
  await page.getByTestId('preset-sunburst').click()
  await page.getByTestId('beat-9').scrollIntoViewIfNeeded()
  await capture(page, size.prefix, 'infect')

  const fake = await context.request.post(`${base}/api/dev/fake-case`, { data: {} })
  const { id } = await fake.json()
  await page.goto(`${base}/cases/${id}`)
  await page.getByTestId('state-detail').waitFor()
  await capture(page, size.prefix, 'live-case')

  const deadline = Date.now() + 25_000
  while (Date.now() < deadline) {
    const detail = await (await context.request.get(`${base}/api/cases/${id}`)).json()
    if (detail.case.state === 'reported') break
    await new Promise((resolve) => setTimeout(resolve, 250))
  }
  await page.reload()
  await page.getByTestId('state-detail').filter({ hasText: 'reported' }).waitFor({ timeout: 20_000 })
  await page.getByTestId('twin-frame').waitFor({ state: 'visible' })
  await capture(page, size.prefix, 'reported-case')

  await page.getByTestId('open-approve').click()
  await page.getByRole('heading', { name: 'Approve what touches the real server' }).waitFor()
  await capture(page, size.prefix, 'approval')
  await page.getByRole('button', { name: 'Close' }).click()

  await page.goto(`${base}/cases/${id}/evidence`)
  await page.getByRole('button', { name: 'Destroy the twin and seal evidence' }).click()
  await page.getByRole('button', { name: /^Yes, destroy/ }).click()
  await page.getByTestId('close-title').filter({ hasText: /^Closed/ }).waitFor({ timeout: 20_000 })
  await capture(page, size.prefix, 'close', true)

  await context.close()
}

await browser.close()
writeFileSync(`${out}/report.json`, JSON.stringify(report, null, 2))
console.log(JSON.stringify(report, null, 2))
