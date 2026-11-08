import { expect, test } from '@playwright/test'
import { signIn } from './auth'

test('analyst console runs a real read-only tool and shows the returned command record', async ({ page, request }) => {
  await signIn(page, request)
  const { id } = await (await request.post('/api/dev/fake-case', { data: {} })).json()
  await page.goto(`/cases/${id}`)
  const panel = page.getByTestId('analyst-console')
  await expect(panel).toContainText('Read-only cloned disk')
  await expect(panel).toContainText('No network')
  await panel.getByRole('button', { name: 'Run tool' }).click()
  const run = panel.getByTestId('analyst-run').first()
  await expect(run).toContainText('cat /mnt/evidence/etc/os-release')
  await expect(run).toContainText('VERSION=24.04.1 LTS')
  await expect(run).toContainText('exit 0')
  await expect(run).toContainText(/\d+ ms/)
})

test('custom script sends editor code and supports keyboard run', async ({ page, request }) => {
  await signIn(page, request)
  const { id } = await (await request.post('/api/dev/fake-case', { data: {} })).json()
  const posts: unknown[] = []
  page.on('request', (r) => { if (r.url().endsWith(`/api/cases/${id}/analyst/run`)) posts.push(r.postDataJSON()) })
  await page.goto(`/cases/${id}`)
  const panel = page.getByTestId('analyst-console')
  await panel.getByRole('tab', { name: 'Write Python' }).click()
  const editor = panel.getByLabel('Python sandbox')
  await expect(editor).toBeVisible()
  await editor.fill('print("verified")')
  await editor.press('Control+Enter')
  await expect(panel.getByTestId('analyst-run').first()).toContainText('verified')
  expect(posts).toEqual([{ tool: 'custom_script', args: { code: 'print("verified")' } }])
})

test('analyst run exposes loading and sandbox errors without inventing output', async ({ page, request }) => {
  await signIn(page, request)
  const { id } = await (await request.post('/api/dev/fake-case', { data: {} })).json()
  await page.route(`**/api/cases/${id}/analyst/run`, async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 150))
    await route.fulfill({ status: 503, json: { detail: 'sandbox runtime unavailable' } })
  })
  await page.goto(`/cases/${id}`)
  const panel = page.getByTestId('analyst-console')
  const run = panel.getByRole('button', { name: 'Run tool' })
  await run.click()
  await expect(panel.getByRole('button', { name: 'Running in sandbox…' })).toBeDisabled()
  await expect(panel.getByRole('alert')).toContainText('sandbox runtime unavailable')
  await expect(panel.getByTestId('analyst-run')).toHaveCount(0)
})
