import { expect, test } from '@playwright/test'

test('/ is the story, outside the operator gate', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByTestId('story')).toBeVisible()
  await expect(page.getByLabel('Operator name')).toHaveCount(0)
})

test('/console in public fake mode auto-starts a demo-judge session', async ({ page }) => {
  const sessions: unknown[] = []
  page.on('request', (request) => {
    if (request.url().endsWith('/api/auth/session') && request.method() === 'POST') sessions.push(request.postDataJSON())
  })
  await page.goto('/console')
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(/Pick the server/)
  await expect(page.getByLabel('Operator name')).toHaveCount(0)
  expect(sessions).toEqual([{ operator: 'demo-judge' }])
})

test('deep link to a case with no session auto-enters that case in public fake mode', async ({ browser, request }) => {
  const s = await request.post('/api/auth/session', { data: { operator: 'seed' } })
  expect(s.ok()).toBe(true)
  const { id } = await (await request.post('/api/dev/fake-case', { data: {} })).json()

  const ctx = await browser.newContext() // fresh: no cookie, no stored operator
  const page = await ctx.newPage()
  await page.goto(`/cases/${id}`)
  await expect(page).toHaveURL(new RegExp(`/cases/${id}$`))
  await expect(page.getByRole('heading', { level: 1 })).toContainText('shop-prod')
  await expect(page.getByLabel('Operator name')).toHaveCount(0)
  await ctx.close()
})
