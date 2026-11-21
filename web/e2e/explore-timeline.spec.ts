import { expect, test } from '@playwright/test'
import { axeSerious, signInAdmin } from './archive-helpers'

// Needs the eval stack (api 8071, the synthetic yellow documents) behind the web origin.
const CLOSED_LETTER = '2024-05-06_merrowby_spine-colour'

test('explore: yellow gives dots by year, the closed letter is a count and never a dot, a dot opens its passage', async ({ page }) => {
  await signInAdmin(page)
  await page.getByRole('button', { name: 'Explore' }).first().click()
  const view = page.getByTestId('explore-view')
  await expect(view).toBeVisible()

  await view.getByLabel('Topic').fill('yellow')
  await view.getByRole('button', { name: 'Explore', exact: true }).click()

  const group = view.getByRole('group', { name: /Documents matching yellow/ })
  const dots = group.locator('button[data-dot]')
  await expect(dots.first()).toBeVisible({ timeout: 30_000 })
  expect(await dots.count()).toBeGreaterThanOrEqual(5)
  for (const i of [0, 1]) {
    const box = (await dots.nth(i).boundingBox())!
    expect(box.width).toBeGreaterThanOrEqual(24)
    expect(box.height).toBeGreaterThanOrEqual(24)
  }
  await expect(group.getByText('Press', { exact: true })).toBeVisible()
  await expect(group.getByText('Ninety Tides', { exact: true })).toBeVisible()
  // The axis labels the years that have documents.
  await expect(group.getByText('2019', { exact: true })).toBeVisible()
  await expect(group.getByText('2026', { exact: true })).toBeVisible()
  // The name carries title, date and how it matched.
  await expect(group.getByRole('button', { name: /yellow-spine-brief_2019-03-12\.md, 12 March 2019, matched the phrase yellow/ })).toBeVisible()

  // Closed items: a count with a reason, never a dot, and the title never reaches the DOM.
  const notOpen = view.getByTestId('not-open')
  await expect(notOpen).toContainText(/Not open to the AI: [1-9]/)
  await expect(notOpen).toContainText('closed by its writer')
  expect(await page.content()).not.toContain(CLOSED_LETTER)
  expect(await page.locator('body').innerText()).not.toContain('merrowby_spine-colour')

  expect(await axeSerious(page, 'explore-view'), 'axe serious/critical on Explore').toEqual([])

  await group.getByRole('button', { name: /yellow-spine-brief_2019-03-12\.md/ }).click()
  const passage = page.getByRole('complementary', { name: 'Passage' })
  await expect(passage.getByRole('heading', { name: 'yellow-spine-brief_2019-03-12.md' })).toBeVisible()
  await expect(passage.getByTestId('passage-text')).toContainText('yellow')
  if (process.env.SHOTS) await page.screenshot({ path: `${process.env.SHOTS}/explore-${page.viewportSize()!.width}.png` })
  expect(await page.content()).not.toContain(CLOSED_LETTER)
})

test('explore: a dot on a PDF shows its page with the passage highlighted, and Open whole file opens it', async ({ page }) => {
  await signInAdmin(page)
  await page.getByRole('button', { name: 'Explore' }).first().click()
  const view = page.getByTestId('explore-view')
  await view.getByLabel('Topic').fill('salt ledger')
  await view.getByRole('button', { name: 'Explore', exact: true }).click()
  const pdfDot = view.locator('button[data-dot][aria-label*=".pdf"]').first()
  await expect(pdfDot).toBeVisible({ timeout: 30_000 })
  await pdfDot.click()
  const passage = page.getByRole('complementary', { name: 'Passage' })
  await expect(passage.getByTestId('passage-highlight').first()).toBeVisible({ timeout: 30_000 })
  await passage.getByRole('button', { name: 'Open whole file' }).click()
  await expect(page.getByAltText(/^Page \d+$/).first()).toBeVisible({ timeout: 30_000 })
})
