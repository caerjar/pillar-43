import { expect, test, type Page } from '@playwright/test'
import { signInAdmin } from './archive-helpers'

// Ribbon, Files gate and phone layout of the org views. Needs the eval-style
// stack with probe-admin / probe-staff / probe-writer accounts.
const STAFF = { name: 'probe-staff', password: 'probe-staff-pw-1' }
const WRITER = { name: 'probe-writer', password: 'probe-writer-pw-1' }

async function signInAs(page: Page, who: { name: string; password: string }) {
  await page.goto('/')
  const form = page.getByRole('form', { name: 'Sign in' })
  await expect(form).toBeVisible({ timeout: 20_000 })
  await form.getByLabel('Name').fill(who.name)
  await form.getByLabel('Password').fill(who.password)
  await form.getByRole('button', { name: 'Sign in' }).click()
  await expect(form).toBeHidden({ timeout: 20_000 })
}

test('files: staff have no Files in the ribbon, an admin has it and it opens the tree', async ({ page, browser }) => {
  await signInAs(page, STAFF)
  await expect(page.getByRole('button', { name: 'Explore' }).first()).toBeVisible()
  await expect(page.getByRole('button', { name: 'Files' })).toHaveCount(0)
  // No empty panel beside Explore.
  await page.getByRole('button', { name: 'Explore' }).first().click()
  await expect(page.locator('.left-panel')).toHaveCount(0)

  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  const admin = await ctx.newPage()
  await signInAdmin(admin)
  await admin.getByRole('button', { name: 'Files' }).click()
  await expect(admin.locator('.left-panel')).toBeVisible()
  await ctx.close()
})

test('ribbon: every destination is named in visible text, with no hover', async ({ page }) => {
  await signInAdmin(page)
  for (const name of ['Ask', 'Explore', 'People', 'Files', 'Settings', 'Sign out']) {
    const b = page.getByRole('button', { name }).first()
    await expect(b).toBeVisible()
    await expect(b).toHaveText(name)
  }
})

test.describe('phone width', () => {
  test.use({ viewport: { width: 390, height: 844 } })
  test('the ribbon is named, and My work does not scroll sideways', async ({ page }) => {
    await signInAs(page, WRITER)
    await expect(page.getByRole('button', { name: 'My work' })).toHaveText('My work')
    await expect(page.getByTestId('terms-view')).toBeVisible({ timeout: 20_000 })
    const over = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
    expect(over).toBeLessThanOrEqual(0)
    const inner = await page.getByTestId('terms-view').evaluate((el) => el.scrollWidth - el.clientWidth)
    expect(inner).toBeLessThanOrEqual(0)
    if (process.env.SHOTS) await page.screenshot({ path: `${process.env.SHOTS}/terms-390.png` })
  })
})
