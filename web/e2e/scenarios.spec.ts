import { expect, test } from '@playwright/test'
import { signIn } from './auth'

// Each preset = the attack set the source's reported technique maps to (src/story/content.ts).
const PRESETS: { id: string; company: string; attacks: string[]; host: string }[] = [
  { id: 'lapsus', company: 'Microsoft', attacks: ['rogue_ssh_key', 'c2_beacon'], host: 'www.microsoft.com' },
  { id: 'sunburst', company: 'SolarWinds', attacks: ['replaced_top', 'c2_beacon'], host: 'cloud.google.com' },
  { id: 'change', company: 'Change Healthcare', attacks: ['rogue_ssh_key', 'c2_beacon'], host: 'techcrunch.com' },
  { id: 'notpetya', company: 'Maersk', attacks: ['replaced_top'], host: 'www.theregister.com' },
]

test('scenarios: each preset posts its attack set and shows its source and the reconstruction label', async ({ page, request }) => {
  await signIn(page, request)
  const posted: string[][] = []
  // Capture the POST and answer 404 (as real mode would) so the page stays put between presets.
  await page.route('**/api/dev/infect', async (r) => {
    posted.push(r.request().postDataJSON().attacks)
    await r.fulfill({ status: 404, json: { detail: 'not here' } })
  })
  await page.goto('/')

  for (const p of PRESETS) {
    await page.getByTestId(`preset-${p.id}`).click()
    await expect(page.getByTestId(`preset-${p.id}`)).toHaveAttribute('aria-pressed', 'true')
    const card = page.getByTestId(`scenario-${p.id}`)
    await expect(card.getByTestId('scenario-label')).toHaveText(`Technique from public reporting. Not data from ${p.company}.`)
    const href = await card.getByTestId('scenario-source').getAttribute('href')
    expect(new URL(href!).host).toBe(p.host)
    for (const a of ['cron_backdoor', 'rogue_ssh_key', 'replaced_top', 'c2_beacon', 'ai_note'])
      await expect(page.getByTestId(`attack-${a}`).locator('input')).toBeChecked({ checked: p.attacks.includes(a) })

    await page.getByTestId('infect').click()
    await expect.poll(() => posted.length).toBe(PRESETS.indexOf(p) + 1)
    expect([...posted.at(-1)!].sort()).toEqual([...p.attacks].sort())
  }

  // Free pick stays available: changing an attack drops the preset card, the toggles still work.
  await page.getByTestId('attack-ai_note').click()
  await expect(page.locator('[data-testid^="scenario-"][data-testid$="notpetya"]')).toHaveCount(0)
  await expect(page.getByTestId('infect')).toHaveText('Infect a server with 2 attacks')
})

test('scenarios: a preset opens a case on a fictional server, not the company\'s', async ({ page, request }) => {
  await signIn(page, request)
  await page.goto('/')
  await page.getByTestId('preset-sunburst').click()
  await page.getByTestId('infect').click()
  await expect(page).toHaveURL(/\/cases\/[\w-]+$/)
  await expect(page.getByRole('heading', { level: 1 })).not.toContainText(/solarwinds/i)
  await expect(page.getByTestId('open-approve')).toHaveText(/Review \d+ proposed actions/, { timeout: 20_000 })
  await expect(page.getByTestId('pane-sandbox').getByTestId('dns-card')).toBeVisible()
})
