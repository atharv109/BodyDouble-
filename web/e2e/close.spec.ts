import { expect, test } from '@playwright/test'
import { signIn } from './auth'

test('close: POST /close, teardown_done shown, blast radius from the backend, bundle downloads as zip', async ({ page, request }) => {
  await signIn(page, request)
  const { id } = await (await request.post('/api/dev/fake-case', { data: {} })).json()
  await expect.poll(async () => (await (await request.get(`/api/cases/${id}`)).json()).case.state, { timeout: 20_000 }).toBe('reported')

  await page.goto(`/cases/${id}/evidence`)
  await expect(page.getByTestId('close-title')).toHaveText('Close the case.')
  await expect(page.getByTestId('download-bundle')).toHaveCount(0) // not before teardown

  // Two clicks: nothing is torn down on the first.
  let closes = 0
  page.on('request', (r) => { if (r.method() === 'POST' && r.url().endsWith(`/cases/${id}/close`)) closes++ })
  await page.getByRole('button', { name: 'Destroy the twin and seal evidence' }).click()
  await page.waitForTimeout(200)
  expect(closes).toBe(0)

  const [res] = await Promise.all([
    page.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith(`/cases/${id}/close`)),
    page.getByRole('button', { name: /^Yes, destroy/ }).click(),
  ])
  expect(res.ok()).toBe(true)
  expect(closes).toBe(1)
  const detail = await res.json()

  // teardown_done arrives over SSE and is shown.
  const td = page.getByTestId('teardown')
  await expect(td).toContainText('teardown_done')
  await expect(td).toContainText('404')
  await expect(page.getByTestId('close-title')).toHaveText('Closed. Nothing escaped.')

  // Blast radius numbers are the backend's, not the UI's.
  for (const k of ['prod_writes_before_approval', 'packets_out', 'containers_left']) {
    await expect(page.getByTestId(`blast-${k}`)).toHaveAttribute('data-value', String(detail.blast_radius[k]))
  }

  // Bundle: GET /cases/{id}/bundle as a zip.
  const [dl] = await Promise.all([page.waitForEvent('download'), page.getByTestId('download-bundle').click()])
  expect(dl.url()).toMatch(new RegExp(`/api/cases/${id}/bundle$`))
  expect(dl.suggestedFilename()).toMatch(/\.zip$/)
  const stream = await dl.createReadStream()
  const head: Buffer = await new Promise((r) => stream.once('data', (b) => r(b as Buffer)))
  expect(head.subarray(0, 2).toString()).toBe('PK') // zip magic
})
