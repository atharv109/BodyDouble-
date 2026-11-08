import { expect, test } from '@playwright/test'
import { signIn } from './auth'
import { offPort } from '../playwright.config'

const live = !!process.env.API_TARGET

test('try it, no session: the gate asks once, then lands on a running case', async ({ page }) => {
  await page.goto('/')
  await page.getByTestId('try-it').click()
  await page.getByLabel('Operator name').fill('e2e-visitor')
  await page.getByRole('button', { name: 'Start session' }).click()
  await expect(page).toHaveURL(/\/cases\/case-\d+$/)
  await expect(page.getByRole('heading', { level: 1 })).toContainText('shop-prod')
  await expect(page.getByTestId('col-twin')).toBeVisible() // the case stream renders
})

test('try it, with a session: straight to the case', async ({ page, request }) => {
  await signIn(page, request)
  await page.goto('/')
  await page.getByTestId('try-it').click()
  await expect(page).toHaveURL(/\/cases\/case-\d+$/)
  await expect(page.getByRole('heading', { level: 1 })).toContainText('shop-prod')
})

test('try it when /dev/fake-case is off: says so, links the console, stays put', async ({ page }) => {
  test.skip(live, 'mock only (needs MOCK_FAKE_CASE_OFF)')
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(String(e)))
  // the browser itself logs the 404 response; anything else on the console is an app error
  page.on('console', (m) => { if (m.type() === 'error' && !m.text().startsWith('Failed to load resource')) errors.push(m.text()) })
  await page.goto(`http://localhost:${offPort}/`)
  await page.getByTestId('try-it').click()
  await page.getByLabel('Operator name').fill('e2e-visitor') // fresh context: the gate asks first
  await page.getByRole('button', { name: 'Start session' }).click()
  const msg = page.getByRole('status').filter({ hasText: 'live demo is not available' })
  await expect(msg).toBeVisible()
  await expect(msg.getByRole('link', { name: /console/i })).toHaveAttribute('href', '/console')
  expect(new URL(page.url()).pathname).toBe('/')
  await expect(page.getByTestId('try-it')).toBeEnabled() // not a dead button
  expect(errors).toEqual([])
})
