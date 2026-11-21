import { expect, test } from '@playwright/test'
import { signInAdmin, signInAs, STAFF } from './archive-helpers'

// Round-2 critic fixes. Needs an org stack with probe-admin and probe-staff.

test('people: each row shows the document count and date range; the record shows a named loading state', async ({ page }) => {
  await page.route('**/api/archive/people/*', async (route) => {
    await new Promise((r) => setTimeout(r, 1500))
    await route.continue()
  })
  await signInAdmin(page)
  await page.getByRole('button', { name: 'People' }).first().click()
  const list = page.getByTestId('people-view').getByRole('list', { name: 'People' })
  const row = list.getByRole('button', { name: /Cassia Merrowby/ })
  await expect(row.getByTestId('person-row-docs')).toHaveText(/^\d+ documents?, \d.*\d{4}$/, { timeout: 20_000 })
  await row.click()
  await expect(page.getByRole('status').filter({ hasText: 'Loading the record of Cassia Merrowby' })).toBeVisible()
  await expect(page.getByRole('article', { name: 'Record: Cassia Merrowby' })).toBeVisible({ timeout: 20_000 })
  // The row count is the record's own count of documents.
  const n = Number((await row.getByTestId('person-row-docs').innerText()).split(' ')[0])
  expect(await page.getByRole('article').locator('button[data-dot]').count()).toBe(n)
})

test('explore: the topic input has a visible focus ring; a markdown passage marks the matched word', async ({ page }) => {
  await signInAdmin(page)
  await page.getByRole('button', { name: 'Explore' }).first().click()
  const view = page.getByTestId('explore-view')
  const input = view.getByLabel('Topic')
  await input.focus()
  await page.keyboard.press('Shift+Tab')
  await page.keyboard.press('Tab')
  const ring = await input.evaluate((el) => {
    const c = getComputedStyle(el)
    return { style: c.outlineStyle, width: parseFloat(c.outlineWidth) }
  })
  expect(ring.style).not.toBe('none')
  expect(ring.width).toBeGreaterThanOrEqual(2)

  await input.fill('yellow')
  await view.getByRole('button', { name: 'Explore', exact: true }).click()
  await view.getByRole('button', { name: /yellow-spine-brief_2019-03-12\.md/ }).click({ timeout: 30_000 })
  const text = page.getByRole('complementary', { name: 'Passage' }).getByTestId('passage-text')
  await expect(text.locator('mark').first()).toHaveText(/yellow/i)
})

test('staff: open whole file from Explore has no Files tab, shows the file and a way back', async ({ page }) => {
  await signInAs(page, STAFF)
  await expect(page.getByRole('button', { name: 'Files' })).toHaveCount(0)
  await page.getByRole('button', { name: 'Explore' }).first().click()
  const view = page.getByTestId('explore-view')
  await view.getByLabel('Topic').fill('yellow')
  await view.getByRole('button', { name: 'Explore', exact: true }).click()
  await view.getByRole('button', { name: /yellow-spine-brief_2019-03-12\.md/ }).click({ timeout: 30_000 })
  await page.getByRole('complementary', { name: 'Passage' }).getByRole('button', { name: 'Open whole file' }).click()
  const back = page.getByRole('button', { name: 'Back to Explore' })
  await expect(back).toBeVisible({ timeout: 20_000 })
  await expect(view).toBeHidden()
  await back.click()
  await expect(page.getByTestId('explore-view')).toBeVisible()
  // The result is still there.
  await expect(page.getByTestId('explore-view').getByRole('button', { name: /yellow-spine-brief_2019-03-12\.md/ })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Back to Explore' })).toHaveCount(0)
})

test('a disabled button keeps its border and is not faded by opacity', async ({ page }) => {
  await signInAdmin(page)
  await page.getByRole('button', { name: 'Explore' }).first().click()
  const go = page.getByTestId('explore-view').getByRole('button', { name: 'Explore', exact: true })
  await expect(go).toBeDisabled()
  const s = await go.evaluate((el) => {
    const c = getComputedStyle(el)
    return { opacity: c.opacity, border: c.borderTopStyle, bg: c.backgroundColor }
  })
  expect(s.opacity).toBe('1')
  expect(s.border).toBe('solid')
  expect(s.bg).not.toBe('rgba(0, 0, 0, 0)')
})
