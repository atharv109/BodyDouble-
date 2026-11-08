import { expect, test } from '@playwright/test'
import { signIn } from './auth'

const EVENTS = [
  'state_changed', 'seal_check', 'step_started', 'step_finished', 'dns_captured',
  'finding_added', 'action_proposed', 'action_applied', 'teardown_done',
]

test('case: a full /dev/fake-case run renders every SSE event type live', async ({ page, request }) => {
  await signIn(page, request)
  const res = await request.post('/api/dev/fake-case', { data: {} })
  expect(res.ok()).toBe(true)
  const { id } = await res.json()

  await page.goto(`/cases/${id}`)
  await expect(page.getByRole('heading', { level: 1 })).toContainText('shop-prod')

  // Production (left): untouched, firewall group shown.
  const prod = page.getByTestId('col-production')
  await expect(prod.getByTestId('lock-badge')).toHaveText(/untouched/)
  await expect(prod.getByTestId('prod-firewall')).toContainText('fw-shop-web')

  // Twin (centre): seal checks pass and the frame seals; steps arrive with code and output.
  const twin = page.getByTestId('col-twin')
  await expect(twin.getByTestId('seal-disk_read_only')).toContainText('passed')
  await expect(twin.getByTestId('seal-egress_blocked')).toContainText('passed')
  await expect(twin.getByTestId('twin-frame')).toHaveAttribute('data-sealed', 'true')
  await expect(twin.getByTestId('rail-sealed')).toHaveAttribute('data-done', 'true')

  // Wait for the agent to finish reporting.
  await expect(twin.getByTestId('state-detail')).toContainText('reported', { timeout: 20_000 })
  const steps = twin.locator('[data-testid^="step-step-"]')
  await expect(steps).toHaveCount(7)
  await expect(twin.locator('[data-status="running"]')).toHaveCount(0)
  const s1 = twin.getByTestId('step-step-01')
  await expect(s1).toContainText('os_facts')
  await expect(s1).toContainText('Establish distro')
  await s1.getByText('Code').click()
  await expect(s1.locator('pre').first()).toContainText('/mnt/evidence/etc/os-release')
  await expect(twin.getByTestId('step-step-06')).toContainText('no-network container')

  // Findings (right): DNS capture card, severity-sorted findings, evidence chips open excerpt + hash.
  const find = page.getByTestId('col-findings')
  await expect(find.getByTestId('dns-card')).toContainText('beacon.c2.example')
  await expect(find.getByTestId('dns-card')).toContainText('10.255.255.1')
  const cards = find.locator('[data-testid^="finding-"][data-severity]')
  await expect(cards).toHaveCount(6)
  const sev = await cards.evaluateAll((els) => els.map((e) => e.getAttribute('data-severity')))
  const rank = { critical: 0, high: 1, medium: 2, info: 3 } as Record<string, number>
  expect(sev.map((s) => rank[s!])).toEqual([...sev.map((s) => rank[s!])].sort((a, b) => a - b))

  await find.getByTestId('chip-ev-008').click()
  const ev8 = find.getByTestId('evidence-ev-008')
  await expect(ev8).toContainText('/root/NOTE_FOR_AI_ANALYST.txt')
  await expect(ev8).toContainText(/[0-9a-f]{64}/)
  await expect(ev8).toContainText('did not follow it')

  // Proposed actions surface as the approve entry point.
  await expect(page.getByTestId('open-approve')).toHaveText(/Review 4 proposed actions/)

  // action_applied and teardown_done arrive live on this screen too (driven via the API here;
  // the approve and close screens have their own specs).
  const approve = await request.post(`/api/cases/${id}/actions/act-1/approve`, { data: { approved_by: 'e2e' } })
  expect(approve.ok()).toBe(true)
  await expect(prod.getByTestId('lock-badge')).toHaveText(/1 approved change/)
  await expect(prod.getByTestId('prod-firewall')).toContainText('fw-0005')

  expect((await request.post(`/api/cases/${id}/close`)).ok()).toBe(true)
  await expect(twin.getByTestId('twin-teardown')).toContainText('404')

  // Every SSE event type was received and rendered.
  const ledger = page.getByTestId('event-ledger')
  for (const e of EVENTS) {
    await expect(ledger.locator(`[data-event="${e}"]`)).not.toHaveAttribute('data-count', '0')
  }
})
