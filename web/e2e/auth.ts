import type { APIRequestContext, Page } from '@playwright/test'

/** Operator session for both the API context (cookie jar) and the page (gate re-mints from the stored name). */
export async function signIn(page: Page, request: APIRequestContext, operator = 'e2e-operator') {
  const r = await request.post('/api/auth/session', { data: { operator } })
  if (!r.ok()) throw new Error(`auth/session -> ${r.status()}`)
  await page.addInitScript((op) => localStorage.setItem('bd.operator', op), operator)
}
