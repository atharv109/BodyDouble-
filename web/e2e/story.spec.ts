import { expect, test, type Page } from '@playwright/test'

const SOURCES = [
  'https://www.pbs.org/newshour/nation/major-us-pipeline-halts-operations-after-ransomware-attack',
  'https://www.bleepingcomputer.com/news/security/largest-us-pipeline-shuts-down-operations-after-ransomware-attack/',
  'https://bleepingcomputer.com/news/security/mgm-resorts-ransomware-attack-led-to-100-million-loss-data-theft/',
  'https://techcrunch.com/2024/06/21/change-healthcare-confirms-ransomware-hackers-stole-medical-records-on-a-substantial-proportion-of-americans',
  'https://www.paubox.com/blog/change-healthcare-ransomware-attack-projected-to-cost-2.3-billion',
  'https://www.theregister.com/2018/01/25/after_notpetya_maersk_replaced_everything',
  'https://www.microsoft.com/security/blog/dev-0537',
  'https://attack.mitre.org/techniques/T1213/005/',
  'https://cloud.google.com/blog/topics/threat-intelligence/sunburst-additional-technical-details/',
]

async function allBeatHeadingsVisible(page: Page) {
  for (let i = 1; i <= 9; i++) {
    const h2 = page.getByTestId(`beat-${i}`).locator('h2').first()
    await h2.scrollIntoViewIfNeeded()
    await expect(h2).toBeVisible()
  }
}

for (const vp of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
  test.describe(`story at ${vp.width}`, () => {
    test.use({ viewport: vp })

    test('nine beats in order, each with an h2, sources linked, no sideways scroll', async ({ page }) => {
      await page.goto('/')
      const ids = await page.locator('[data-testid^="beat-"]').evaluateAll((els) => els.map((e) => e.getAttribute('data-testid')))
      expect(ids).toEqual(Array.from({ length: 9 }, (_, i) => `beat-${i + 1}`))
      for (let i = 1; i <= 9; i++) await expect(page.getByTestId(`beat-${i}`).locator('h2')).not.toHaveCount(0)
      for (const url of SOURCES) await expect(page.locator(`a[href="${url}"]`).first()).toBeAttached()
      await expect(page.getByTestId('beat-9').getByTestId('try-it')).toBeAttached()
      // walk the whole page, then check overflow (late layout included)
      await allBeatHeadingsVisible(page)
      const over = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
      expect(over).toBeLessThanOrEqual(0)
    })

    test('reduced motion: every beat heading readable', async ({ page }) => {
      await page.emulateMedia({ reducedMotion: 'reduce' })
      await page.goto('/')
      await allBeatHeadingsVisible(page)
    })

    test('no WebGL: the whole story still reads', async ({ page }) => {
      await page.addInitScript(() => {
        const orig = HTMLCanvasElement.prototype.getContext
        // @ts-expect-error narrowing the overloads is not the point here
        HTMLCanvasElement.prototype.getContext = function (type: string, ...rest: unknown[]) {
          if (String(type).startsWith('webgl')) return null
          // @ts-expect-error see above
          return orig.call(this, type, ...rest)
        }
      })
      const errors: string[] = []
      page.on('pageerror', (e) => errors.push(String(e)))
      await page.goto('/')
      await allBeatHeadingsVisible(page)
      expect(errors).toEqual([])
    })
  })
}
