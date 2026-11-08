import { expect, test } from '@playwright/test'
import { signIn } from './auth'

test('terminal: each pane gets its events from the fake case, live and on replay', async ({ page, request }) => {
  await signIn(page, request)
  const res = await request.post('/api/dev/fake-case', { data: {} })
  expect(res.ok()).toBe(true)
  const { id } = await res.json()

  const check = async () => {
    const cmd = page.getByTestId('pane-commands')
    const ai = page.getByTestId('pane-ai')
    const sbx = page.getByTestId('pane-sandbox')
    const log = page.getByTestId('pane-log')
    await expect(page.getByTestId('state-detail')).toContainText(/reported|contained|closed/, { timeout: 20_000 })

    // Commands + output: exact code, stdout, exit code and duration per step.
    await expect(cmd.locator('[data-testid^="step-step-"]')).toHaveCount(7)
    const s1 = cmd.getByTestId('step-step-01')
    await expect(s1).toContainText('$ cat /mnt/evidence/etc/os-release')
    await expect(s1).toContainText('Ubuntu 24.04.1 LTS')
    await expect(s1).toContainText(/\[exit 0 · \d+ ms\]/)

    // AI reasoning: planner picks tool + args + rationale; solver lands findings, then the report and ranked fixes.
    await expect(ai.getByTestId('ai-step-05')).toContainText('planner')
    await expect(ai.getByTestId('ai-step-05')).toContainText('/usr/local/bin/.sysupd.sh')
    await expect(ai.getByTestId('ai-step-05')).toContainText('Pull the cron payload')
    await expect(ai.getByTestId('ai-fd-01')).toContainText('solver')
    await expect(ai.locator('[data-testid^="finding-"][data-severity]')).toHaveCount(6)
    await expect(ai.getByTestId('ai-report')).toContainText('report')
    await expect(ai.locator('[data-testid^="rank-"]').first()).toContainText('recommended')

    // Sandbox / network: the detonation and its DNS capture into the sinkhole.
    await expect(sbx.getByTestId('sbx-step-06')).toContainText('detonate')
    await expect(sbx).toContainText('beacon.c2.example -> 10.255.255.1')
    await expect(sbx.getByTestId('dns-card')).toBeVisible()

    // Seal + case log: seal output, state changes, proposed actions with their Vultr call.
    const seal = log.getByTestId('seal-disk_read_only')
    await expect(seal).toContainText('passed')
    await expect(seal.locator('pre')).toHaveText(/\S/) // the check's raw output (mock and live word it differently)
    await expect(log).toContainText('investigating')
    await expect(log.getByTestId('log-proposed-act-1')).toContainText('PATCH /v2/instances/')
  }

  await page.goto(`/cases/${id}`)
  await check()

  // Approve + close: the log carries the applied call and the teardown, the sandbox meters end at 0.
  expect((await request.post(`/api/cases/${id}/actions/act-1/approve`, { data: { approved_by: 'e2e' } })).ok()).toBe(true)
  expect((await request.post(`/api/cases/${id}/close`)).ok()).toBe(true)
  const log = page.getByTestId('pane-log')
  await expect(log.getByTestId('log-applied-act-1')).toContainText('applied by e2e')
  await expect(log.getByTestId('twin-teardown')).toContainText('404')
  await expect(page.getByTestId('packets-out')).toHaveText('0')
  await expect(page.getByTestId('containers-left')).toHaveText('0')

  // Replay: opening the finished case rebuilds every pane from the stream.
  await page.reload()
  await check()
  await expect(page.getByTestId('pane-log').getByTestId('twin-teardown')).toContainText('404')
  await expect(page.getByTestId('packets-out')).toHaveText('0')
})

test('terminal: attacker stdout renders as text, never HTML', async ({ page }) => {
  const id = 'case-xss'
  const evil = '<img src=x onerror=alert(1)>'
  const step = { id: 'step-01', case_id: id, seq: 1, kind: 'triage', tool: 'os_facts', args: {}, rationale: 'r',
    code: 'cat /mnt/evidence/etc/motd', stdout: evil, stderr: '', exit_code: 0, duration_ms: 5 }
  const detail = {
    case: { id, instance_id: 'inst-x', instance_label: 'x-prod', reason: 'test', state: 'investigating',
      created_at: '2026-11-08T00:00:00Z' },
    steps: [step], evidence: [], findings: [], actions: [],
  }
  const sse = [
    ['state_changed', { case_id: id, from_state: 'sealed', to_state: 'investigating', detail: evil }],
    ['step_started', { step }],
    ['step_finished', { step }],
  ].map(([e, d], i) => `event: ${e}\nid: ${i}\ndata: ${JSON.stringify(d)}\n\n`).join('')

  await page.addInitScript(() => localStorage.setItem('bd.operator', 'e2e'))
  await page.route('**/api/auth/**', (r) => r.fulfill({ json: { operator: 'e2e', password_required: false } }))
  await page.route('**/api/instances', (r) => r.fulfill({ json: [] }))
  await page.route(`**/api/cases/${id}`, (r) => r.fulfill({ json: detail }))
  await page.route(`**/api/cases/${id}/stream`, (r) => r.fulfill({ contentType: 'text/event-stream', body: sse }))
  let dialog = false
  page.on('dialog', (d) => { dialog = true; d.dismiss() })

  await page.goto(`/cases/${id}`)
  await expect(page.getByTestId('pane-commands').getByTestId('step-step-01')).toContainText(evil)
  await expect(page.getByTestId('state-detail')).toContainText(evil)
  await expect(page.locator('[data-testid="col-twin"] img')).toHaveCount(0)
  expect(dialog).toBe(false)
})
