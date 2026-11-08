// Jury evidence for screens that live behind a click (approve drawer, close screen), which shoot.mjs can't reach.
// node scripts/shoot-states.mjs <approve|close> <outDir>   (needs vite preview on :4400 against a mock)
import { chromium } from 'playwright'
import { readFileSync, mkdirSync, writeFileSync } from 'node:fs'
import { createRequire } from 'node:module'

const [which, out] = process.argv.slice(2)
const BASE = 'http://127.0.0.1:4400'
mkdirSync(out, { recursive: true })
const axeSrc = readFileSync(createRequire(import.meta.url).resolve('axe-core/axe.min.js'), 'utf8')
const report = { which, shots: [], axe: {} }

const b = await chromium.launch()
const ctx = await b.newContext()
await ctx.request.post(`${BASE}/api/auth/session`, { data: { operator: 'qa' } })
const { id } = await (await ctx.request.post(`${BASE}/api/dev/fake-case`, { data: {} })).json()
await new Promise((r) => setTimeout(r, 14000)) // let the mock finish reporting

async function axe(p, name) {
  await p.addScriptTag({ content: axeSrc })
  const r = await p.evaluate(async () => (await window.axe.run()).violations.map((v) => ({ id: v.id, impact: v.impact, n: v.nodes.length })))
  report.axe[name] = r
}
async function shot(p, name) { await p.screenshot({ path: `${out}/${name}.png` }); report.shots.push(name) }

for (const [w, h, pre] of [[1440, 900, 'd'], [390, 844, 'm']]) {
  const p = await b.newPage({ viewport: { width: w, height: h } })
  await p.addInitScript(() => localStorage.setItem('bd.operator', 'qa'))
  if (which === 'approve') {
    await p.goto(`${BASE}/cases/${id}`)
    await p.getByTestId('open-approve').click()
    await p.waitForTimeout(500)
    await shot(p, `${pre}-01-open`); await axe(p, `${pre}-open`)
    if (pre === 'd') {
      await p.getByTestId('action-act-1').getByRole('checkbox').check()
      await shot(p, `${pre}-02-checked`)
      await p.getByTestId('approve-submit').hover(); await shot(p, `${pre}-03-hover-approve`)
      await p.getByTestId('approve-submit').click(); await p.waitForTimeout(600)
      await shot(p, `${pre}-04-applied`); await axe(p, `${pre}-applied`)
      await p.keyboard.press('Tab'); await shot(p, `${pre}-05-focus`)
    }
  } else {
    await p.goto(`${BASE}/cases/${id}/evidence`)
    await p.waitForTimeout(800)
    await shot(p, `${pre}-01-before`); await axe(p, `${pre}-before`)
    if (pre === 'd') {
      const btn = p.getByRole('button', { name: /Destroy the twin/ })
      await btn.hover(); await shot(p, `${pre}-02-hover`)
      await btn.click()
      await p.getByRole('button', { name: /Yes, destroy/ }).click()
      await p.waitForTimeout(800)
      await shot(p, `${pre}-03-after`); await axe(p, `${pre}-after`)
    } else {
      // phone: closed state too
    }
  }
  await p.close()
}
await b.close()
writeFileSync(`${out}/report.json`, JSON.stringify(report, null, 2))
console.log(JSON.stringify(report.axe))
