import { createRequire } from 'node:module'
import { mkdirSync } from 'node:fs'
import { expect, test, type Browser, type Page } from '@playwright/test'

// The writer's terms view ("My work") on the eval stack (pillar43-eval, api 8071).
//
// Setup (a data change on the eval stack, already applied; harmless to repeat):
//   docker exec pillar43-eval-api-1 python scripts/archive_cli.py owner probe-writer \
//     library/contracts/Kaminrowska_Lanterns_translation-contract_signed-2020-02-17.pdf
//   plus a staff account: probe-staff / probe-staff-pw-1 (accounts API, loopback).
// Run against your own web origin proxying /api to 8071:
//   API_PROXY_TARGET=http://127.0.0.1:8071 npx vite --port 5223
//   PILLAR43_URL=http://127.0.0.1:5223/ npx playwright test terms-writer
//
// The close-and-re-ask test closes the Lanterns contract and ALWAYS restores it
// to `model` through the same visible control in a finally step. The withdraw
// test never completes a withdrawal (that is irreversible): it intercepts the
// POST. Other agents run ask specs on this stack, so nothing here waits on them.
const WRITER = { name: 'probe-writer', password: 'probe-writer-pw-1' }
const STAFF = { name: 'probe-staff', password: 'probe-staff-pw-1' }
const QUESTION = 'Where are we allowed to sell the Lanterns book, and is it paperback only?'
const SHOTS = process.env.TERMS_SHOTS_DIR

async function signIn(page: Page, who: { name: string; password: string }) {
  await page.goto('/')
  const form = page.getByRole('form', { name: 'Sign in' })
  await expect(form).toBeVisible({ timeout: 20_000 })
  await form.getByLabel('Name').fill(who.name)
  await form.getByLabel('Password').fill(who.password)
  await form.getByRole('button', { name: 'Sign in' }).click()
  await expect(form).toBeHidden({ timeout: 20_000 })
}

async function asWriter(browser: Browser) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  const page = await ctx.newPage()
  await signIn(page, WRITER)
  await expect(page.getByTestId('terms-view')).toBeVisible({ timeout: 20_000 })
  return { ctx, page }
}

const lanterns = (page: Page) => page.getByRole('row').filter({ hasText: 'Lanterns' })

async function setLevel(page: Page, name: RegExp) {
  const radio = lanterns(page).getByRole('radio', { name })
  const done = page.waitForResponse((r) => r.url().includes('/api/archive/items/consent') && r.ok())
  await radio.click()
  await done
  await expect(radio).toBeChecked()
}

test('terms: a writer lands on My work and sees only their own items, titled, with all three levels written out', async ({ browser }) => {
  const { ctx, page } = await asWriter(browser)
  try {
    await expect(page.getByRole('button', { name: 'My work' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Ask', exact: true })).toHaveCount(0)
    const row = lanterns(page)
    await expect(row).toHaveCount(1)
    await expect(row.getByRole('rowheader')).toContainText('Lanterns')
    // a title, not a filename
    await expect(row.getByRole('rowheader')).not.toContainText('.pdf')
    for (const [n, meaning] of [
      ['Private', /the AI never reads it/],
      ['Staff', /Staff can search and cite it/],
      ['Model', /The AI may read it to answer staff questions/],
    ] as const) {
      await expect(row.getByRole('radio', { name: new RegExp('^' + n) })).toBeVisible()
      await expect(row.getByText(meaning).first()).toBeVisible()
    }
    // Only their own: the API says so and refuses everyone else.
    const mine = await page.request.get('/api/archive/my-work')
    const body = await mine.json()
    expect(body.items.map((i: { path: string }) => i.path)).toEqual([expect.stringContaining('Lanterns')])
    if (SHOTS) {
      mkdirSync(SHOTS, { recursive: true })
      await page.screenshot({ path: `${SHOTS}/terms-1440x900.png` })
      await page.setViewportSize({ width: 390, height: 844 })
      await page.screenshot({ path: `${SHOTS}/terms-390x844.png` })
    }
  } finally {
    await ctx.close()
  }
})

test('terms: set the level to Staff and back to Model from the visible control', async ({ browser }) => {
  const { ctx, page } = await asWriter(browser)
  try {
    await setLevel(page, /^Staff/)
    await page.reload()
    await expect(lanterns(page).getByRole('radio', { name: /^Staff/ })).toBeChecked()
  } finally {
    await setLevel(page, /^Model/)
    await ctx.close()
  }
})

test('terms: set a label and take it off; the notice states its meaning in words', async ({ browser }) => {
  const { ctx, page } = await asWriter(browser)
  try {
    const row = lanterns(page)
    const add = row.getByRole('button', { name: /^Add label attribution required/ })
    const done = page.waitForResponse((r) => r.url().includes('/api/archive/items/labels') && r.ok())
    await add.click()
    await done
    await expect(row.getByText('Whoever uses it must credit the writer.')).toBeVisible()
    await expect(row.getByRole('button', { name: /^Remove label attribution required/ })).toBeVisible()
  } finally {
    const remove = lanterns(page).getByRole('button', { name: /^Remove label attribution required/ })
    if (await remove.count()) {
      const done = page.waitForResponse((r) => r.url().includes('/api/archive/items/labels') && r.ok())
      await remove.click()
      await done
    }
    await ctx.close()
  }
})

test('terms: withdraw confirms in place, with no browser dialog; Keep it posts nothing', async ({ browser }) => {
  const { ctx, page } = await asWriter(browser)
  let dialogs = 0
  let withdrawPosts = 0
  page.on('dialog', (d) => { dialogs++; void d.dismiss() })
  await page.route('**/api/archive/withdraw', (route) => {
    withdrawPosts++
    // Never reaches the archive: a withdrawal cannot be undone.
    return route.fulfill({ status: 500, body: '{"detail":"blocked by the spec"}', contentType: 'application/json' })
  })
  try {
    const row = lanterns(page)
    await row.getByRole('button', { name: /^Withdraw / }).click()
    await expect(row.getByText(/The archive forgets it and cannot take it back/)).toBeVisible()
    await row.getByRole('button', { name: 'Keep it' }).click()
    await expect(row.getByText(/cannot take it back/)).toHaveCount(0)
    expect(withdrawPosts).toBe(0)
    await row.getByRole('button', { name: /^Withdraw / }).click()
    await row.getByRole('button', { name: 'Yes, withdraw' }).click()
    await expect.poll(() => withdrawPosts).toBe(1)
    await expect(row.getByRole('alert')).toBeVisible() // the failure is said in the row
    expect(dialogs).toBe(0)
  } finally {
    await ctx.close()
  }
})

test('terms: the access log shows date, purpose and receipt for each time the AI read the item, never the question', async ({ browser }) => {
  const { ctx, page } = await asWriter(browser)
  try {
    const body = await (await page.request.get('/api/archive/my-work')).json()
    expect(JSON.stringify(body)).not.toMatch(/paperback|allowed to sell/i)
    const row = lanterns(page)
    const log = row.getByRole('list', { name: /^Access log for/ })
    if (body.items[0].reads.length === 0) {
      await expect(row.getByText('Not read by the AI.')).toBeVisible()
      test.info().annotations.push({ type: 'note', description: 'no reads on this stack yet; log rendering is covered by vitest' })
      return
    }
    await expect(log.getByRole('listitem').first()).toHaveText(/^\d{4}-\d{2}-\d{2}, .+, answer receipt \d+$/)
    await expect(row.getByText(/^Read (once|\d+ times)$/)).toBeVisible()
  } finally {
    await ctx.close()
  }
})

test('terms: staff and admin have no My work', async ({ browser }) => {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  const page = await ctx.newPage()
  try {
    await signIn(page, STAFF)
    await expect(page.getByRole('button', { name: 'Sign out' })).toBeVisible({ timeout: 20_000 })
    await expect(page.getByRole('button', { name: 'My work' })).toHaveCount(0)
    expect((await page.request.get('/api/archive/my-work')).status()).toBe(403)
  } finally {
    await ctx.close()
  }
})

test('terms: axe finds no serious or critical violation on My work, at 1440 and 390 wide', async ({ browser }) => {
  const { ctx, page } = await asWriter(browser)
  try {
    const axeSrc = createRequire(import.meta.url)('axe-core').source as string
    for (const size of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
      await page.setViewportSize(size)
      await page.evaluate(axeSrc)
      const bad = await page.evaluate(async () => {
        const r = await (window as unknown as { axe: { run: (o: unknown) => Promise<{ violations: { id: string; impact: string; nodes: unknown[] }[] }> } }).axe.run({ include: ["[data-testid=terms-view]"] } as never)
        return r.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical').map((v) => `${v.id} x${v.nodes.length}`)
      })
      expect(bad, `axe at ${size.width}`).toEqual([])
    }
    // 24 px minimum targets
    for (const el of await lanterns(page).getByRole('button').all()) {
      expect((await el.boundingBox())!.height).toBeGreaterThanOrEqual(24)
    }
  } finally {
    await ctx.close()
  }
})

test('terms: the writer closes the Lanterns contract, staff ask q001 and see it declined with the closure named', async ({ browser }) => {
  test.setTimeout(240_000)
  const writer = await asWriter(browser)
  try {
    // Close it to the AI from the writer's own screen: level Staff (staff may
    // still see it, the AI never reads it). Private would hide it from staff
    // altogether, and the archive only counts what staff cannot see, never names it.
    await setLevel(writer.page, /^Staff/)

    const staffCtx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
    const staff = await staffCtx.newPage()
    try {
      await signIn(staff, STAFF)
      await staff.getByLabel('Question').fill(QUESTION)
      await staff.getByTestId("ask-view").getByRole("button", { name: "Ask" }).click()
      await expect(staff.getByRole('region', { name: 'Answer' })).toContainText('It is closed by its writer, so the AI did not read it.', { timeout: 120_000 })
      const silences = staff.getByTestId('silences')
      await expect(silences).toContainText('closed by its writer')
      await expect(silences).toContainText('Lanterns')
      if (SHOTS) {
        mkdirSync(SHOTS, { recursive: true })
        await staff.screenshot({ path: `${SHOTS}/ask-declined-1440x900.png` })
      }
    } finally {
      await staffCtx.close()
    }
  } finally {
    // Restore through the same visible control.
    await setLevel(writer.page, /^Model/)
    await writer.ctx.close()
  }
})
