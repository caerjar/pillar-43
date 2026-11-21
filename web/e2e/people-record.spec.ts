import { expect, test } from '@playwright/test'
import { axeSerious, signInAdmin } from './archive-helpers'

const CLOSED_LETTER = '2024-05-06_merrowby_spine-colour'

test('people: open Cassia Merrowby from the list, see her record, click a dot to its page', async ({ page }) => {
  await signInAdmin(page)
  await page.getByRole('button', { name: 'People' }).first().click()
  const view = page.getByTestId('people-view')
  await view.getByRole('list', { name: 'People' }).getByRole('button', { name: /Cassia Merrowby/ }).click()

  const record = view.getByRole('article', { name: 'Record: Cassia Merrowby' })
  await expect(record.getByRole('heading', { name: 'Cassia Merrowby' })).toBeVisible({ timeout: 20_000 })
  await expect(record).toContainText('author of The Salt Ledger, Ninety Tides')
  await expect(record.getByRole('list', { name: 'Titles' })).toContainText('The Salt Ledger')

  await expect(record.locator('button[data-dot]').first()).toBeVisible()
  const signed = record.getByRole('button', { name: /contract_merrowby_SaltLedger_2012\.pdf, 14 September 2012, signed/ })
  await expect(signed).toBeVisible()
  await expect(record.getByRole('button', { name: /catalog\.csv, .*mentioned/ })).toBeVisible()

  const notOpen = record.getByTestId('not-open')
  await expect(notOpen).toContainText(/Not open to the AI: [1-9]/)
  await expect(notOpen).toContainText('closed by their writers')
  expect(await page.content()).not.toContain(CLOSED_LETTER)
  expect(await page.locator('body').innerText()).not.toContain('merrowby_spine-colour')

  expect(await axeSerious(page, 'people-view'), 'axe serious/critical on People').toEqual([])
  if (process.env.SHOTS) await page.screenshot({ path: `${process.env.SHOTS}/people-${page.viewportSize()!.width}.png` })

  await signed.click()
  const passage = page.getByRole('complementary', { name: 'Passage' })
  await expect(passage).toContainText('signed')
  await expect(passage.getByTestId('passage-highlight').first()).toBeVisible({ timeout: 30_000 })
  await passage.getByRole('button', { name: 'Open whole file' }).click()
  await expect(page.getByAltText(/^Page \d+$/).first()).toBeVisible({ timeout: 30_000 })
})

test('people: the record shows the date range, a counted line per connection kind and a labelled heading', async ({ page }) => {
  await signInAdmin(page)
  await page.getByRole('button', { name: 'People' }).first().click()
  const view = page.getByTestId('people-view')
  await view.getByRole('list', { name: 'People' }).getByRole('button', { name: /Cassia Merrowby/ }).click()
  const record = view.getByRole('article', { name: 'Record: Cassia Merrowby' })
  await expect(record.getByTestId('person-dates')).toHaveText(/^Documents dated \d/, { timeout: 20_000 })
  await expect(record.getByTestId('person-kinds')).toHaveText(/\d+ signed/)
  await expect(record.getByTestId('person-kinds')).toHaveText(/\d+ mentioned/)
  await expect(record.getByRole('heading', { name: 'Titles and documents' })).toBeVisible()
})
