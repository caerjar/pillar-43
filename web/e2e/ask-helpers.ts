import { createRequire } from 'node:module'
import { expect, type Page } from '@playwright/test'

// Needs an org stack with the synthetic press and accounts, and a web origin
// proxying /api to it (see org-signin.spec.ts). Not a spec file.
export const ADMIN = { name: 'probe-admin', password: 'probe-admin-pw-1' }
// The Drowned Orchard and Weather for Ferrymen are safe to ask about; the
// Lanterns contract is closed and reopened by other specs.
export const QUESTION = 'Who holds the translation rights to The Drowned Orchard and when do they revert?'

/** Sign in from the visible form when the stack has accounts. */
export async function openAsk(page: Page) {
  await page.goto('/')
  const form = page.getByRole('form', { name: 'Sign in' })
  const ask = page.getByTestId('ask-view')
  await expect(form.or(ask)).toBeVisible({ timeout: 30_000 })
  if (await form.isVisible()) {
    await form.getByLabel('Name').fill(ADMIN.name)
    await form.getByLabel('Password').fill(ADMIN.password)
    await form.getByRole('button', { name: 'Sign in' }).click()
  }
  await expect(ask).toBeVisible({ timeout: 30_000 })
}

/** Ask from the visible field and wait for the answer. Returns the response body. */
export async function askQuestion(page: Page, q = QUESTION) {
  await page.getByLabel('Question').fill(q)
  const answered = page.waitForResponse(
    (r) => r.url().includes('/api/archive/ask') && r.request().method() === 'POST',
    { timeout: 150_000 },
  )
  await page.getByTestId('ask-view').getByRole('button', { name: 'Ask', exact: true }).click()
  const body = await (await answered).json()
  await expect(page.getByRole('region', { name: 'Answer' })).toBeVisible()
  return body
}

/** axe-core is a transitive dependency, not @axe-core/playwright: inject it. */
export async function axeViolations(page: Page, scope = '[data-testid="ask-view"]'): Promise<string[]> {
  const src = createRequire(import.meta.url)('axe-core').source as string
  await page.evaluate(src)
  return page.evaluate(async (scope) => {
    type R = { violations: { id: string; impact: string | null; nodes: { target: unknown[] }[] }[] }
    const r = await (window as unknown as { axe: { run: (c: unknown) => Promise<R> } }).axe.run({ include: [scope] })
    return r.violations
      .filter((v) => v.impact === 'serious' || v.impact === 'critical')
      .map((v) => `${v.id} (${v.impact}) x${v.nodes.length} ${v.nodes.map((n) => n.target.join(' ')).join(' | ')}`)
  }, scope)
}
