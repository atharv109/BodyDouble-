import { expect, test } from '@playwright/test'
import { signIn } from './auth'

test('approve: one POST per checked action, only after the click, each response shown', async ({ page, request }) => {
  await signIn(page, request)
  const { id } = await (await request.post('/api/dev/fake-case', { data: {} })).json()

  const approvals: { url: string; body: unknown }[] = []
  page.on('request', (r) => {
    if (r.method() === 'POST' && /\/actions\/[^/]+\/approve$/.test(r.url())) approvals.push({ url: r.url(), body: r.postDataJSON() })
  })

  await page.goto(`/cases/${id}`)
  const open = page.getByTestId('open-approve')
  await expect(open).toHaveText(/Review 4 proposed actions/, { timeout: 20_000 })
  await open.click()

  const drawer = page.getByTestId('approve-drawer')
  await expect(drawer).toBeVisible()
  await expect(drawer.getByRole('heading', { level: 2 })).toHaveText('Approve what touches the real server')

  // Every proposed action shows its exact API call; no-API kinds say so.
  await expect(drawer.getByTestId('call-act-1')).toContainText('PATCH /v2/instances/inst-shop-prod')
  await expect(drawer.getByTestId('call-act-1')).toContainText('"firewall_group_id": "fw-0005"')
  await expect(drawer.getByTestId('call-act-3')).toContainText('POST /v2/instances/inst-shop-prod/halt')
  await expect(drawer.getByTestId('call-act-2')).toContainText('No API call')

  // Nothing is pre-checked; the button is inert until something is ticked.
  const submit = drawer.getByTestId('approve-submit')
  for (const a of ['act-1', 'act-2', 'act-3', 'act-4']) await expect(drawer.getByTestId(`action-${a}`).getByRole('checkbox')).not.toBeChecked()
  await expect(submit).toBeDisabled()

  await drawer.getByTestId('action-act-1').getByRole('checkbox').check()
  await drawer.getByTestId('action-act-2').getByRole('checkbox').check()
  await page.waitForTimeout(300)
  expect(approvals).toHaveLength(0) // ticking sends nothing

  await expect(submit).toHaveText('Approve 2 actions')
  await submit.click()

  await expect(drawer.getByTestId('response-act-1')).toContainText('202 PATCH /v2/instances/inst-shop-prod')
  await expect(drawer.getByTestId('response-act-2')).toContainText('no API call made')
  await expect(drawer.getByTestId('action-act-1')).toHaveAttribute('data-status', 'applied')

  expect(approvals.map((a) => a.url.replace(/^.*\/cases\//, '/cases/'))).toEqual([
    `/cases/${id}/actions/act-1/approve`,
    `/cases/${id}/actions/act-2/approve`,
  ])
  for (const a of approvals) expect(a.body).toEqual({ approved_by: 'e2e-operator' })

  // Unticked actions were left alone.
  await expect(drawer.getByTestId('action-act-3')).toHaveAttribute('data-status', 'proposed')
  await expect(drawer.getByTestId('action-act-4')).toHaveAttribute('data-status', 'proposed')

  // Production column reflects the approved change once the drawer closes.
  await drawer.getByRole('button', { name: 'Close' }).click()
  await expect(page.getByTestId('lock-badge')).toHaveText(/2 approved changes/)
  await expect(page.getByTestId('prod-firewall')).toContainText('fw-0005')
})
