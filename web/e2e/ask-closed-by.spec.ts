import { expect, test } from '@playwright/test'
import { askQuestion, openAsk } from './ask-helpers'

// "Not in this answer" says who closed the items, never "by their writers" for
// items the intake default closed (feature audit 2026-11-20, H1).
test('ask: each closed group names who closed it, from the response', async ({ page }) => {
  await openAsk(page)
  const body = await askQuestion(page)
  const legend = page.getByRole('complementary', { name: 'Not in this answer' })
  await expect(legend).toBeVisible()
  const by = body.silences.closed_by as { writer: number; default: number; staff: number }
  expect(by.writer + by.default + by.staff).toBe(body.silences.closed)
  const text = (await legend.textContent()) ?? ''
  if (by.writer > 0) expect(text).toMatch(/closed by (its|their) writers?/)
  else expect(text).not.toMatch(/writer/)
  if (by.default > 0) expect(text).toContain('closed by default (no one has opened')
  else expect(text).not.toContain('closed by default')
  if (by.staff > 0) expect(text).toContain('closed by staff or an administrator')
})

// A title with no document of the asked kind is said to have none, not answered
// from other titles' contracts (feature audit 2026-11-20, H4b). The synthetic
// press holds a design note and letters about Ninety Tides but no contract.
test('ask: a title with no contract says so instead of borrowing other contracts', async ({ page }) => {
  await openAsk(page)
  await askQuestion(page, 'What did the Ninety Tides contract say about royalties?')
  const answer = page.getByRole('region', { name: 'Answer' })
  await expect(answer).toContainText('There is no contract for Ninety Tides in the archive.')
  await expect(page.getByTestId('silences')).toContainText('There is no contract for Ninety Tides in the archive')
  await expect(answer.getByLabel(/^Source \d$/)).toHaveCount(0)
})
