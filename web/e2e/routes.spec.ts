import { expect, test } from '@playwright/test'

test('/ is the story, outside the operator gate', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByTestId('story')).toBeVisible()
  await expect(page.getByLabel('Operator name')).toHaveCount(0)
})

test('/console shows the gate, then Servers after sign-in', async ({ page }) => {
  await page.goto('/console')
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Who is operating?')
  await page.getByLabel('Operator name').fill('e2e-operator')
  await page.getByRole('button', { name: 'Start session' }).click()
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(/Pick the server/)
})

test('deep link to a case with no session: gate first, then that case', async ({ browser, request }) => {
  const s = await request.post('/api/auth/session', { data: { operator: 'seed' } })
  expect(s.ok()).toBe(true)
  const { id } = await (await request.post('/api/dev/fake-case', { data: {} })).json()

  const ctx = await browser.newContext() // fresh: no cookie, no stored operator
  const page = await ctx.newPage()
  await page.goto(`/cases/${id}`)
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Who is operating?')
  await page.getByLabel('Operator name').fill('e2e-operator')
  await page.getByRole('button', { name: 'Start session' }).click()
  await expect(page).toHaveURL(new RegExp(`/cases/${id}$`))
  await expect(page.getByRole('heading', { level: 1 })).toContainText('shop-prod')
  await ctx.close()
})
