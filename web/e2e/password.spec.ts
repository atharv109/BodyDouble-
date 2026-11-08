import { expect, test } from '@playwright/test'

// Real mode: GET /auth/config says password_required, the gate asks for a password and sends it.
// Mock: a second control plane with MOCK_PASSWORD=e2e-secret on :5180. Live: needs E2E_PASSWORD.
const live = !!process.env.API_TARGET
const password = live ? process.env.E2E_PASSWORD : 'e2e-secret'
test.use({ baseURL: live ? undefined : 'http://localhost:5180' })

test('password gate: field shown when required, wrong password inline, right one signs in', async ({ page, request }) => {
  test.skip(!password, 'live run without E2E_PASSWORD')
  const cfg = await (await request.get('/api/auth/config')).json()
  test.skip(!cfg.password_required, 'backend is in fake mode (no password)')

  const sessions: unknown[] = []
  page.on('request', (r) => { if (r.url().endsWith('/api/auth/session') && r.method() === 'POST') sessions.push(r.postDataJSON()) })

  await page.goto('/console')
  await expect(page.getByRole('heading', { level: 1, name: 'Who is operating?' })).toBeVisible()
  const pw = page.getByLabel('Operator password')
  await expect(pw).toHaveAttribute('type', 'password')
  await expect(pw).toHaveAttribute('autocomplete', 'current-password')

  await page.getByLabel('Operator name').fill('e2e-operator')
  const start = page.getByRole('button', { name: 'Start session' })
  await expect(start).toBeDisabled() // no password yet
  await pw.fill('not-the-password')
  await start.click()
  await expect(page.getByRole('alert')).toHaveText('Wrong operator password')
  await expect(page.getByRole('heading', { level: 1, name: 'Who is operating?' })).toBeVisible()

  await pw.fill(password!)
  await page.getByRole('button', { name: 'Start session' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Pick the server that worries you.' })).toBeVisible()
  expect(sessions).toEqual([
    { operator: 'e2e-operator', password: 'not-the-password' },
    { operator: 'e2e-operator', password },
  ])
})

test('fake mode bypasses the operator gate', async ({ page }) => {
  test.skip(live, 'mock only')
  await page.goto('http://localhost:5179/console')
  await expect(page.getByRole('heading', { level: 1, name: 'Pick the server that worries you.' })).toBeVisible()
  await expect(page.getByLabel('Operator name')).toHaveCount(0)
  await expect(page.getByLabel('Operator password')).toHaveCount(0)
})
