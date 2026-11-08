import { expect, test } from '@playwright/test'

test('servers: list, investigate modal, POST /cases, land on case screen', async ({ page }) => {
  // Public fake mode creates the fixed demo judge session and opens the console directly.
  await page.goto('/console')
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(/Pick the server/)
  await expect(page.getByLabel('Operator name')).toHaveCount(0)

  const row = page.getByTestId('server-inst-shop-prod')
  await expect(row).toContainText('shop-prod')
  await expect(row).toContainText('ewr')
  await expect(row).toContainText('45.77.10.20')
  await expect(row).toContainText('active')
  await expect(page.getByRole('button', { name: /^Investigate / })).toHaveCount(await page.locator('tbody tr').count())

  await row.getByRole('button', { name: 'Investigate shop-prod' }).click()
  const dialog = page.getByRole('dialog', { name: 'Investigate shop-prod' })
  await expect(dialog).toBeVisible()

  const submit = dialog.getByRole('button', { name: 'Open case' })
  await expect(submit).toBeDisabled() // reason is required

  // Cancel closes without a request.
  let posted = 0
  page.on('request', (r) => { if (r.method() === 'POST' && r.url().endsWith('/api/cases')) posted++ })
  await dialog.getByRole('button', { name: 'Cancel' }).click()
  await expect(dialog).toBeHidden()
  expect(posted).toBe(0)

  await row.getByRole('button', { name: 'Investigate shop-prod' }).click()
  await dialog.getByLabel('What looks wrong?').fill('CPU at 100% overnight, unknown process.')
  const [req] = await Promise.all([
    page.waitForRequest((r) => r.method() === 'POST' && r.url().endsWith('/api/cases')),
    submit.click(),
  ])
  expect(req.postDataJSON()).toEqual({ instance_id: 'inst-shop-prod', reason: 'CPU at 100% overnight, unknown process.' })
  const res = await req.response()
  expect(res?.ok()).toBe(true)
  const { id } = await res!.json()

  await expect(page).toHaveURL(new RegExp(`/cases/${id}$`))
  await expect(page.getByRole('heading', { level: 1 })).toContainText('shop-prod')
})
