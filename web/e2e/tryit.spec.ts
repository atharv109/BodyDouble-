import { expect, test } from '@playwright/test'
import { signIn } from './auth'
import { offPort } from '../playwright.config'

const live = !!process.env.API_TARGET

test('infect, no session: the gate asks once, then lands on the case the sensor opened', async ({ page }) => {
  await page.goto('/')
  await page.getByTestId('attack-cron_backdoor').click()
  await page.getByTestId('infect').click()
  await page.getByLabel('Operator name').fill('e2e-visitor')
  await page.getByRole('button', { name: 'Start session' }).click()
  await expect(page).toHaveURL(/\/cases\/[\w-]+$/)
  await expect(page.getByRole('heading', { level: 1 })).toContainText('and its twin')
  await expect(page.getByTestId('case-alert')).toContainText('Sensor alert')
  await expect(page.getByTestId('col-twin')).toBeVisible() // the case stream renders
})

test('infect, with a session: straight to the case', async ({ page, request }) => {
  await signIn(page, request)
  await page.goto('/')
  await page.getByTestId('attack-c2_beacon').click()
  await page.getByTestId('infect').click()
  await expect(page).toHaveURL(/\/cases\/[\w-]+$/)
  await expect(page.getByRole('status')).toContainText('Demo sensor opened this real case record')
  await expect(page.getByTestId('case-alert')).toBeVisible()
})

test('one attack picked: only that attack\'s findings land', async ({ page, request }) => {
  await signIn(page, request)
  await page.goto('/')
  await page.getByTestId('attack-rogue_ssh_key').click()
  await expect(page.getByTestId('infect')).toHaveText('Infect a server with 1 attack')
  await page.getByTestId('infect').click()
  await expect(page).toHaveURL(/\/cases\/[\w-]+$/)
  // ATTACK_FINDINGS: rogue_ssh_key -> fd-02 only; ATTACK_ACTIONS adds act-2 to the three always proposed.
  await expect(page.getByTestId('open-approve')).toHaveText(/Review 4 proposed actions/, { timeout: 20_000 })
  const findings = page.getByTestId('col-findings').locator('li[data-testid^="finding-"]')
  await expect(findings).toHaveCount(1)
  await expect(findings.first()).toContainText('SSH key')
})

test('infect when /dev/infect is off: says so, links the console, stays put', async ({ page }) => {
  test.skip(live, 'mock only (needs MOCK_FAKE_CASE_OFF)')
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(String(e)))
  // the browser itself logs the 404 response; anything else on the console is an app error
  page.on('console', (m) => { if (m.type() === 'error' && !m.text().startsWith('Failed to load resource')) errors.push(m.text()) })
  await page.goto(`http://localhost:${offPort}/`)
  await page.getByTestId('infect').click()
  await page.getByLabel('Operator name').fill('e2e-visitor') // fresh context: the gate asks first
  await page.getByRole('button', { name: 'Start session' }).click()
  const msg = page.getByRole('status').filter({ hasText: 'live demo is not available' })
  await expect(msg).toBeVisible()
  await expect(msg.getByRole('link', { name: /console/i })).toHaveAttribute('href', '/console')
  expect(new URL(page.url()).pathname).toBe('/')
  await expect(page.getByTestId('infect')).toBeEnabled() // not a dead button
  expect(errors).toEqual([])
})
