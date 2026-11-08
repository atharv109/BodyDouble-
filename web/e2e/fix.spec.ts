import { expect, test, type APIRequestContext, type Page } from '@playwright/test'
import { signIn } from './auth'

async function openDrawer(page: Page, request: APIRequestContext) {
  await signIn(page, request)
  const { id } = await (await request.post('/api/dev/fake-case', { data: {} })).json()
  await page.goto(`/cases/${id}`)
  const open = page.getByTestId('open-approve')
  await expect(open).toHaveText(/Review 4 proposed actions/, { timeout: 20_000 })
  await open.click()
  return { id, drawer: page.getByTestId('approve-drawer') }
}

test('the recommended fix stands out; the others are alternatives', async ({ page, request }) => {
  const { drawer } = await openDrawer(page, request)
  const rec = drawer.getByTestId('fix-recommended')
  await expect(rec.getByRole('heading')).toHaveText('Recommended fix')
  await expect(rec.locator('li')).toHaveCount(1)
  await expect(rec.getByTestId('action-act-1')).toHaveAttribute('data-recommended', 'true')
  await expect(rec.getByTestId('action-act-1')).toContainText('recommended')
  const alts = drawer.getByTestId('fix-alternatives')
  for (const a of ['act-2', 'act-3', 'act-4']) await expect(alts.getByTestId(`action-${a}`)).toBeVisible()
  // The recommended fix comes first in reading order.
  const order = await drawer.locator('li[data-testid^="action-"]').evaluateAll((els) => els.map((e) => e.getAttribute('data-testid')))
  expect(order[0]).toBe('action-act-1')
  // Nothing pre-checked, recommended or not.
  await expect(rec.getByRole('checkbox')).not.toBeChecked()
})

test('your own plan: posted as kind + description, then the same Approve; never an API call', async ({ page, request }) => {
  const { id, drawer } = await openDrawer(page, request)
  const posts: { url: string; body: unknown }[] = []
  page.on('request', (r) => { if (r.method() === 'POST' && /\/cases\/[^/]+\/actions(\/|$)/.test(r.url())) posts.push({ url: r.url(), body: r.postDataJSON() }) })

  const form = drawer.getByTestId('custom-fix')
  await form.getByLabel('Add your own fix').selectOption('manual_plan')
  await form.getByLabel('Your plan').fill('Rebuild from a clean image tonight, restore the database from Tuesday.')
  const [res] = await Promise.all([
    page.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith(`/cases/${id}/actions`)),
    form.getByTestId('custom-submit').click(),
  ])
  expect(res.ok()).toBe(true)
  const mine = await res.json()
  expect(posts[0].body).toEqual({ kind: 'manual_plan', description: 'Rebuild from a clean image tonight, restore the database from Tuesday.', created_by: 'e2e-operator' })

  const row = drawer.getByTestId('fix-own').getByTestId(`action-${mine.id}`)
  await expect(row).toHaveAttribute('data-status', 'proposed')
  await expect(row).toHaveAttribute('data-created-by', 'human')
  await expect(row).toContainText('yours')
  await expect(row.getByTestId(`call-${mine.id}`)).toContainText('never executes it')
  await expect(row.getByRole('checkbox')).not.toBeChecked() // added unticked: still needs Approve
  expect(posts.filter((p) => p.url.endsWith('/approve'))).toHaveLength(0)

  await row.getByRole('checkbox').check()
  await expect(drawer.getByTestId('approve-submit')).toHaveText('Approve 1 action')
  await drawer.getByTestId('approve-submit').click()
  await expect(row).toHaveAttribute('data-status', 'applied')
  await expect(drawer.getByTestId(`response-${mine.id}`)).toContainText('no API call made')
  expect(posts.filter((p) => p.url.endsWith('/approve')).map((p) => p.url.replace(/^.*\/cases\//, '/cases/')))
    .toEqual([`/cases/${id}/actions/${mine.id}/approve`])
})

test('your own menu fix: the backend builds the call, shown before you approve', async ({ page, request }) => {
  const { drawer } = await openDrawer(page, request)
  const form = drawer.getByTestId('custom-fix')
  await form.getByLabel('Add your own fix').selectOption('stop_instance')
  await form.getByLabel('Why, in your words').fill('Halt it now; the shop can be down for an hour.')
  const [res] = await Promise.all([
    page.waitForResponse((r) => r.request().method() === 'POST' && /\/actions$/.test(r.url())),
    form.getByTestId('custom-submit').click(),
  ])
  const mine = await res.json()
  expect(res.request().postDataJSON()).not.toHaveProperty('api_path') // the client never sends a path or body
  const row = drawer.getByTestId(`action-${mine.id}`)
  await expect(row.getByTestId(`call-${mine.id}`)).toContainText('POST /v2/instances/inst-shop-prod/halt')
  await expect(row).toHaveAttribute('data-status', 'proposed')
})
