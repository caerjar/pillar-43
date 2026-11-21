import { createRequire } from 'node:module'
import { expect, test } from '@playwright/test'

// Sign-in in the org profile, from the visible fields. Needs an org stack with
// accounts (probe-writer / probe-writer-pw-1 on pillar43-eval, api 8071) and a
// web origin proxying /api to it, e.g.
//   API_PROXY_TARGET=http://127.0.0.1:8071 npx vite --port 5225
//   PILLAR43_URL=http://127.0.0.1:5225/ npx playwright test org-signin
const WRITER = { name: 'probe-writer', password: 'probe-writer-pw-1' }

test('a wrong password shows the error line, the right one continues to the app, Sign out returns', async ({ page }) => {
  await page.goto('/')
  const form = page.getByRole('form', { name: 'Sign in' })
  await expect(form).toBeVisible({ timeout: 20_000 })

  // axe-core is a transitive dependency, not @axe-core/playwright: inject it.
  const axeSrc = createRequire(import.meta.url)('axe-core').source as string
  await page.evaluate(axeSrc)
  const axe = await page.evaluate(async () => {
    const r = await (window as unknown as { axe: { run: () => Promise<{ violations: { id: string; nodes: unknown[] }[] }> } }).axe.run()
    return r.violations.map((v) => `${v.id} x${v.nodes.length}`)
  })
  expect(axe, 'axe violations on the sign-in screen').toEqual([])

  for (const el of [form.getByLabel('Name'), form.getByLabel('Password'), form.getByRole('button', { name: 'Sign in' })]) {
    const box = (await el.boundingBox())!
    expect(box.height).toBeGreaterThanOrEqual(24)
  }

  await form.getByLabel('Name').fill(WRITER.name)
  await form.getByLabel('Password').fill('not-the-password')
  await form.getByRole('button', { name: 'Sign in' }).click()
  await expect(form.getByRole('alert')).toHaveText('Wrong name or password.')
  await expect(form).toBeVisible()

  await form.getByLabel('Password').fill(WRITER.password)
  await form.getByRole('button', { name: 'Sign in' }).click()
  await expect(form).toBeHidden({ timeout: 20_000 })
  // A writer has no Ask view; the signed-in shell is up and Sign out is in the ribbon.
  const signOut = page.getByRole('button', { name: 'Sign out' })
  await expect(signOut).toBeVisible({ timeout: 20_000 })

  await signOut.click()
  await expect(page.getByRole('form', { name: 'Sign in' })).toBeVisible({ timeout: 20_000 })
})
