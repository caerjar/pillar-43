import { expect, test } from '@playwright/test'
import { signInAdmin } from './archive-helpers'

test.use({ viewport: { width: 390, height: 844 } })

test('explore and people at phone width keep every dot reachable', async ({ page }) => {
  await signInAdmin(page)
  await page.getByRole('button', { name: 'Explore' }).first().click()
  const view = page.getByTestId('explore-view')
  await view.getByLabel('Topic').fill('yellow')
  await view.getByRole('button', { name: 'Explore', exact: true }).click()
  const dots = view.locator('button[data-dot]')
  await expect(dots.first()).toBeVisible({ timeout: 30_000 })
  const vw = 390
  for (let i = 0; i < (await dots.count()); i++) {
    const box = (await dots.nth(i).boundingBox())!
    expect(box.x).toBeGreaterThanOrEqual(0)
    expect(box.x + box.width).toBeLessThanOrEqual(vw)
    expect(box.width).toBeGreaterThanOrEqual(24)
  }
  if (process.env.SHOTS) await page.screenshot({ path: `${process.env.SHOTS}/explore-390.png` })

  await page.getByRole('button', { name: 'People' }).first().click()
  await page.getByTestId('people-view').getByRole('button', { name: /Cassia Merrowby/ }).click()
  await expect(page.getByRole('heading', { name: 'Cassia Merrowby' })).toBeVisible({ timeout: 20_000 })
  if (process.env.SHOTS) await page.screenshot({ path: `${process.env.SHOTS}/people-390.png` })
})
