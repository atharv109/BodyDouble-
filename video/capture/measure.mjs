// measure: exact Y positions of the case-screen panes, to script scroll choreography
import pw from 'file:///C:/dev/wt-video/web/node_modules/playwright/index.mjs'

const BACK = 'http://localhost:8010'
const APP = 'http://localhost:4273'
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

async function mint() {
  const res = await fetch(BACK + '/auth/session', {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ operator: 'demo' }),
  })
  return res.headers.get('set-cookie').split(';')[0]
}

const cookie = await mint()
await fetch(BACK + '/dev/fake-case', {
  method: 'POST', headers: { cookie, 'content-type': 'application/json' },
  body: JSON.stringify({ reason: 'layout probe' }),
}).catch(() => {})
for (let i = 0; i < 40; i++) {
  await sleep(300)
  try {
    const c = await mint()
    const res = await fetch(BACK + '/cases/case-0001', { headers: { cookie: c } })
    if (res.ok) break
  } catch {}
}
const browser = await pw.chromium.launch()
const ctx = await browser.newContext({ viewport: { width: 1920, height: 1080 } })
await ctx.addInitScript(() => localStorage.setItem('bd.operator', 'demo'))
const page = await ctx.newPage()
await page.goto(APP + '/cases/case-0001')
await page.waitForSelector('[data-testid="ai-report"]', { timeout: 40000 })
await sleep(1000)
const info = await page.evaluate(() => {
  const r = (sel) => {
    const el = document.querySelector(sel)
    if (!el) return null
    const b = el.getBoundingClientRect()
    return { top: +b.top.toFixed(0), bottom: +b.bottom.toFixed(0), left: +b.left.toFixed(0), right: +b.right.toFixed(0) }
  }
  return {
    docHeight: document.documentElement.scrollHeight,
    els: {
      header: r('header h1'),
      colProduction: r('[data-testid="col-production"]'),
      twinFrame: r('[data-testid="twin-frame"]'),
      statusBar: r('[data-testid="state-detail"]'),
      paneCommands: r('.pane-commands'),
      paneAi: r('.pane-ai'),
      paneSandbox: r('.pane-sandbox'),
      paneLog: r('.pane-log'),
      dnsCard: r('[data-testid^="sbx-dns-"]'),
      sealStatus: r('[data-testid="seal-status"]'),
      sandboxMeters: r('[data-testid="sandbox-meters"]'),
      eventLedger: r('[data-testid="event-ledger"]'),
    },
  }
})
console.log(JSON.stringify(info, null, 2))
await browser.close()
