// Body Double — product footage capture. Real app only: backend :8000 (FakeVultr,
// POLL_INTERVAL_S raised for legible state polling — see video/claims.md),
// built frontend on :4173 (vite preview, /api proxied).
//
// pass A: console list + Investigate dialog + typed reason + submit (ends on busy)
// pass B: full case story, live SSE (snapshot->seal->cascade->report), approve, close
// pass C: sensor alert inbox + auto-opened case (dev/infect with all five attacks)
import pw from 'file:///C:/dev/wt-video/web/node_modules/playwright/index.mjs'
import { mkdirSync, writeFileSync, cpSync, rmSync } from 'node:fs'

const BACK = 'http://localhost:8010'
const APP = 'http://localhost:4273'
const RAW = 'C:/dev/wt-video/video/capture/raw'
const REASON = 'CPU at 100% overnight, unknown process.'
const ATTACKS = ['cron_backdoor', 'rogue_ssh_key', 'replaced_top', 'c2_beacon', 'ai_note']

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const markers = {}
const mark = (pass, name, start) => {
  const t = +((Date.now() - start) / 1000).toFixed(2)
  ;(markers[pass] ??= []).push({ name, t })
  console.log(`  [${pass}] ${name} @ ${t}s`)
}

async function mint() {
  const res = await fetch(BACK + '/auth/session', {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ operator: 'demo' }),
  })
  if (!res.ok) throw new Error('mint failed: ' + res.status)
  return res.headers.get('set-cookie').split(';')[0]
}
const api = (method, path, cookie, body) => fetch(BACK + path, {
  method, headers: { cookie, 'content-type': 'application/json' },
  body: body === undefined ? undefined : JSON.stringify(body),
})

async function newPass(browser) {
  const ctx = await browser.newContext({
    viewport: { width: 1920, height: 1080 },
    deviceScaleFactor: 2,
    recordVideo: { dir: RAW, size: { width: 3840, height: 2160 } },
  })
  await ctx.addInitScript(() => localStorage.setItem('bd.operator', 'demo'))
  const page = await ctx.newPage()
  page.on('pageerror', (e) => console.log('  pageerror:', e.message))
  return { ctx, page, start: Date.now() }
}
const scrollTo = (page, top) => page.evaluate((t) => window.scrollTo({ top: t, behavior: 'smooth' }), top)

mkdirSync(RAW, { recursive: true })
const browser = await pw.chromium.launch()

// ---------------------------------------------------------------- pass A
console.log('pass A: console + investigate dialog')
{
  const A = await newPass(browser)
  await A.page.goto(APP + '/console')
  await A.page.waitForSelector('[data-testid="server-inst-shop-prod"]', { timeout: 20000 })
  mark('A', 'console loaded', A.start)
  await sleep(1500)
  await A.page.locator('[data-testid="server-inst-shop-prod"]').hover()
  await sleep(1000)
  mark('A', 'row hovered', A.start)
  await A.page.click('button[aria-label="Investigate shop-prod"]')
  await A.page.waitForSelector('dialog[open] textarea', { timeout: 10000 })
  await sleep(800)
  await A.page.click('dialog[open] textarea')
  await A.page.keyboard.type(REASON, { delay: 52 })
  mark('A', 'reason typed', A.start)
  await sleep(700)
  await A.page.click('dialog[open] button[type="submit"]')
  mark('A', 'open case clicked', A.start)
  await sleep(1600) // busy state "Opening case..." — end before it resolves
  const v = A.page.video()
  await A.ctx.close()
  markers.A ??= []
  markers.A.video = await v.path()
}

// ---------------------------------------------------------------- pass B
console.log('pass B: full case story (live)')
{
  const cookie = await mint()
  // fire and forget: the POST runs the whole case server-side; we must not await it,
  // so the browser can attach to the SSE stream while the case is still walking.
  const running = api('POST', '/dev/fake-case', cookie, { reason: REASON })
    .then((r) => r.json()).then((c) => { markers.B ??= [{ name: 'fake-case resolved', t: 0 }]; console.log('  fake-case resolved:', c.id, c.state) }).catch((e) => console.log('  fake-case promise:', e.message))

  let caseId = null
  for (let i = 0; i < 80; i++) {
    await sleep(250)
    try {
      const c = await mint() // sessions were wiped with the db; keep re-minting
      const res = await api('GET', '/cases/case-0001', c)
      if (res.ok) { caseId = 'case-0001'; break }
    } catch { /* not up yet */ }
  }
  if (!caseId) throw new Error('case-0001 never appeared')
  console.log('  case exists; opening case screen')

  const B = await newPass(browser)
  await B.page.goto(APP + '/cases/' + caseId)
  await B.page.waitForSelector('[data-testid="rail-snapshotting"], [data-testid="rail-restoring"], [data-testid="rail-sealed"], [data-testid="rail-investigating"]', { timeout: 20000 })
  mark('B', 'case screen live', B.start)
  await sleep(1500)

  await B.page.waitForSelector('[data-testid="seal-status"]:has-text("sealed")', { timeout: 40000 })
  mark('B', 'sealed', B.start)
  await sleep(1200)
  await scrollTo(B.page, 400) // frame the seal + log and sandbox row (measured: y 920-1336)
  await sleep(2600) // perimeter draws, checks read [ ok ]

  await B.page.waitForSelector('[data-testid="ai-report"]', { timeout: 40000 })
  mark('B', 'reported (cascade done)', B.start)
  await sleep(1200)
  await scrollTo(B.page, 0) // report + ranked fixes in the AI pane
  await sleep(3200)

  // dwell on the sandbox DNS capture + meters
  await scrollTo(B.page, 400)
  mark('B', 'dns hold begins', B.start)
  await sleep(3600)

  // approval
  await scrollTo(B.page, 0)
  await sleep(600)
  await B.page.click('[data-testid="open-approve"]')
  await B.page.waitForSelector('[data-testid="approve-drawer"][open]', { timeout: 10000 })
  mark('B', 'approve drawer open', B.start)
  await sleep(1400)
  await B.page.click('[data-testid="fix-recommended"] input[type="checkbox"]')
  await sleep(900)
  await B.page.click('[data-testid="approve-submit"]')
  mark('B', 'approve clicked', B.start)
  await B.page.waitForSelector('[data-testid="approve-drawer"] [data-testid^="response-"]', { timeout: 20000 })
  await sleep(1000)
  mark('B', 'api response shown', B.start)
  await sleep(2200)
  await B.page.click('[data-testid="approve-drawer"] header button:has-text("Close")')
  await sleep(900)

  // close + evidence
  await B.page.click('a:has-text("Close and evidence")')
  await B.page.waitForSelector('[data-testid="blast"]', { timeout: 15000 })
  mark('B', 'close screen', B.start)
  await sleep(2200)
  await B.page.click('button:has-text("Destroy the twin and seal evidence")')
  await sleep(700)
  await B.page.click('button:has-text("Yes, destroy")')
  mark('B', 'teardown confirmed', B.start)
  await B.page.waitForSelector('[data-testid="close-title"]:has-text("Closed")', { timeout: 30000 })
  mark('B', 'closed', B.start)
  await sleep(4200)
  const v = B.page.video()
  await B.ctx.close()
  markers.B.video = await v.path()
  await running
}

// ---------------------------------------------------------------- pass C
console.log('pass C: sensor alert + auto-opened case')
{
  const cookie = await mint()
  const res = await api('POST', '/dev/infect', cookie, { attacks: ATTACKS })
  if (!res.ok) throw new Error('infect failed: ' + res.status)
  const { case_id: caseC } = await res.json()
  console.log('  infect case:', caseC)
  for (let i = 0; i < 80; i++) {
    await sleep(500)
    const c = await mint()
    const detail = await (await api('GET', '/cases/' + caseC, c)).json()
    if (detail.case.state === 'reported') break
  }
  const C = await newPass(browser)
  await C.page.goto(APP + '/console')
  await C.page.waitForSelector('[data-testid^="alert-"]', { timeout: 20000 })
  mark('C', 'console with alert', C.start)
  await sleep(1800)
  await C.page.locator('[data-testid^="alert-"]').first().hover()
  await sleep(1200)
  await C.page.click(`a[href="/cases/${caseC}"]`)
  await C.page.waitForSelector('[data-testid="ai-report"]', { timeout: 20000 })
  mark('C', 'auto case opened', C.start)
  await sleep(4200)
  const v = C.page.video()
  await C.ctx.close()
  markers.C.video = await v.path()
}

await browser.close()
writeFileSync('C:/dev/wt-video/video/capture/markers.json', JSON.stringify(markers, null, 2))
console.log('done.')
