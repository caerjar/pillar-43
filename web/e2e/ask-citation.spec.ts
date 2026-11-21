import { expect, test } from '@playwright/test'
import { askQuestion, axeViolations, openAsk } from './ask-helpers'

// ask -> citation -> the PDF page with the cited clause highlighted on it.
// Uses the live model, so it asserts structure, not wording.
test('ask: a citation opens the PDF page with the clause highlighted', async ({ page }) => {
  await openAsk(page)
  const body = await askQuestion(page)
  expect(body.not_answered).toBe(false)

  // The first answer sentence that cites a PDF passage.
  const sentence = body.answer.find((s: { cites: number[] }) =>
    s.cites.some((n) => body.passages.find((p: { n: number; path: string }) => p.n === n)?.path.endsWith('.pdf')))
  expect(sentence, 'a cited PDF passage').toBeTruthy()
  const n = sentence.cites.find((c: number) => body.passages.find((p: { n: number; path: string }) => p.n === c)?.path.endsWith('.pdf'))
  const passage = body.passages.find((p: { n: number }) => p.n === n)
  expect(passage.page, 'PDF passages carry a page').toBeGreaterThan(0)

  await page.getByRole('button', { name: `Source ${n}`, exact: true }).first().click()
  const source = page.getByRole('complementary', { name: 'Source' })
  await expect(source).toBeVisible()

  // Titled by item and work, never by file name.
  const heading = await source.getByRole('heading').textContent()
  expect(heading).not.toMatch(/\.pdf|library\//)
  if (passage.isbn) await expect(source.getByText(`ISBN ${passage.isbn}`).first()).toBeVisible()

  // The page image and a highlight laid over it.
  const image = source.getByRole('img', { name: /^Page \d+$/ })
  await expect(image).toBeVisible({ timeout: 30_000 })
  const highlight = source.getByTestId('passage-highlight').first()
  await expect(highlight).toBeVisible({ timeout: 30_000 })
  const imgBox = (await image.boundingBox())!
  const hl = (await highlight.boundingBox())!
  expect(hl.width).toBeGreaterThan(40)
  expect(hl.height).toBeGreaterThan(6)
  expect(hl.x).toBeGreaterThanOrEqual(imgBox.x)
  expect(hl.x + hl.width).toBeLessThanOrEqual(imgBox.x + imgBox.width + 1)
  expect(hl.y).toBeGreaterThanOrEqual(imgBox.y)
  expect(hl.y + hl.height).toBeLessThanOrEqual(imgBox.y + imgBox.height + 1)

  expect(await axeViolations(page), 'axe with the source open').toEqual([])

  await source.getByRole('button', { name: 'Close source' }).click()
  await expect(source).toBeHidden()
})
