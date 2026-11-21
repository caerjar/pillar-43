import { expect, test } from '@playwright/test'
import { askQuestion, axeViolations, openAsk } from './ask-helpers'

test('ask: the empty state names what is open to the AI, by kind', async ({ page }) => {
  await openAsk(page)
  const region = page.getByRole('region', { name: 'Open to the AI' })
  await expect(region).toBeVisible({ timeout: 20_000 })
  // The numbers are the API's, not counted in the browser.
  const api = await (await page.request.get('/api/archive/open-to-ai')).json()
  await expect(region.getByRole('heading')).toHaveText(`Open to the AI: ${api.total} ${api.total === 1 ? 'item' : 'items'}`)
  await expect(region.getByRole('listitem')).toHaveCount(api.by_kind.length)
  for (const k of api.by_kind) {
    await expect(region.getByRole('listitem').filter({ hasText: k.kind }).first()).toContainText(String(k.count))
  }
  expect(await axeViolations(page), 'axe on the empty Ask screen').toEqual([])
})

test('ask: Stop ends the wait, keeps the question and shows no error', async ({ page }) => {
  await openAsk(page)
  const q = 'Who holds the translation rights to Weather for Ferrymen?'
  await page.getByLabel('Question').fill(q)
  await page.getByTestId('ask-view').getByRole('button', { name: 'Ask', exact: true }).click()
  const status = page.getByRole('status').filter({ hasText: /Answering/ })
  await expect(status).toBeVisible()
  await expect(status).toHaveText(/Answering… [1-9]\d* s/, { timeout: 10_000 })
  await page.getByRole('button', { name: 'Stop' }).click()
  await expect(status).toBeHidden()
  await expect(page.getByRole('alert')).toHaveCount(0)
  await expect(page.getByLabel('Question')).toHaveValue(q)
  await expect(page.getByLabel('Question')).toBeEnabled()
})

test('ask: the answer sits beside what it could not say; 24 px targets; axe is clean', async ({ page }) => {
  await openAsk(page)
  const body = await askQuestion(page)
  const legend = page.getByRole('complementary', { name: 'Not in this answer' })
  await expect(legend).toBeVisible()
  // One plain line per kind, with its count, from the response.
  if (body.silences.closed > 0) {
    await expect(legend.getByRole('listitem').first()).toContainText(String(body.silences.closed))
  }
  // Beside the answer in the same layout: the two share a row at this width.
  const a = (await page.getByRole('region', { name: 'Answer' }).boundingBox())!
  const l = (await legend.boundingBox())!
  expect(l.x).toBeGreaterThan(a.x + a.width - 1)
  expect(Math.abs(l.y - a.y)).toBeLessThan(40)
  // Not an error or warning colour: the lines are set in the answer's own text colour.
  const [legendColor, answerColor] = await page.evaluate(() => [
    getComputedStyle(document.querySelector('[aria-label="Not in this answer"] li')!).color,
    getComputedStyle(document.querySelector('[aria-label="Answer"] p')!).color,
  ])
  expect(legendColor).toBe(answerColor)

  const small: string[] = []
  const buttons = page.getByTestId('ask-view').getByRole('button')
  for (let i = 0; i < (await buttons.count()); i++) {
    const b = buttons.nth(i)
    const box = await b.boundingBox()
    if (box && (box.width < 24 || box.height < 24)) small.push(`${await b.textContent()} ${box.width}x${box.height}`)
  }
  expect(small, 'targets under 24 px').toEqual([])

  expect(await axeViolations(page), 'axe on an answered Ask screen').toEqual([])
})
