import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'
import { signIn } from './auth'

async function noSeriousViolations(page: Page) {
  const { violations } = await new AxeBuilder({ page }).analyze()
  const bad = violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')
  expect(bad.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).slice(0, 3).join(', ')}`)).toEqual([])
}

for (const vp of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
  test.describe(`a11y at ${vp.width}`, () => {
    test.use({ viewport: vp })

    test('story', async ({ page }) => {
      await page.emulateMedia({ reducedMotion: 'reduce' }) // everything at its final state
      await page.goto('/')
      await expect(page.getByTestId('beat-9')).toBeAttached()
      await noSeriousViolations(page)
    })

    test('console (signed in)', async ({ page, request }) => {
      await signIn(page, request)
      await page.goto('/console')
      await expect(page.getByRole('heading', { level: 1 })).toHaveText(/Pick the server/)
      await noSeriousViolations(page)
    })

    test('running case', async ({ page, request }) => {
      await signIn(page, request)
      const { id } = await (await request.post('/api/dev/fake-case', { data: {} })).json()
      await page.goto(`/cases/${id}`)
      await expect(page.getByTestId('col-twin')).toBeVisible()
      await noSeriousViolations(page)
    })
  })
}
