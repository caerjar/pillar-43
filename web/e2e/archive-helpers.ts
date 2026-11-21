import { createRequire } from 'node:module'
import { expect, type Page } from '@playwright/test'

export const ADMIN = { name: 'probe-admin', password: 'probe-admin-pw-1' }

export const STAFF = { name: 'probe-staff', password: 'probe-staff-pw-1' }

export async function signInAdmin(page: Page) {
  return signInAs(page, ADMIN)
}

export async function signInAs(page: Page, who: { name: string; password: string }) {
  await page.goto('/')
  const form = page.getByRole('form', { name: 'Sign in' })
  await expect(form).toBeVisible({ timeout: 20_000 })
  await form.getByLabel('Name').fill(who.name)
  await form.getByLabel('Password').fill(who.password)
  await form.getByRole('button', { name: 'Sign in' }).click()
  await expect(form).toBeHidden({ timeout: 20_000 })
}

/** Serious or critical axe violations on the current page. */
/** `scope` is a test id: the shell's own menubar and resize handle are not these views. */
export async function axeSerious(page: Page, scope: string): Promise<string[]> {
  const axeSrc = createRequire(import.meta.url)('axe-core').source as string
  await page.evaluate(axeSrc)
  return page.evaluate(async (testId) => {
    type R = { violations: { id: string; impact: string | null; nodes: { target: unknown }[] }[] }
    const r = await (window as unknown as { axe: { run: (ctx: string) => Promise<R> } }).axe.run(`[data-testid="${testId}"]`)
    return r.violations
      .filter((v) => v.impact === 'serious' || v.impact === 'critical')
      .map((v) => `${v.id} ${JSON.stringify(v.nodes.map((n) => n.target))}`)
  }, scope)
}
