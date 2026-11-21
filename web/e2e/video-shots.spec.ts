import { mkdirSync } from 'node:fs'
import { expect, test, type Page } from '@playwright/test'

// Screen recordings for the 2-minute video (work/archive/video-kit.md).
// Tagged @video and excluded from the default run (grepInvert in
// playwright.config.ts, lifted by VIDEO_RUN=1). Run against the recording
// stack (pillar43-video, web 5241), on the synthetic press:
//   VIDEO_RUN=1 npx playwright test --grep @video
// Every shot signs in through the visible sign-in screen and works through the
// visible controls only. Each test is one shot and saves its clip to
// VIDEO_OUT/shot-<n>.webm.
//
// Configurable by env: VIDEO_URL (or PILLAR43_URL), VIDEO_OUT, and per role
// VIDEO_ADMIN / VIDEO_STAFF / VIDEO_WRITER as "name:password".
// Eval-stack dry run: VIDEO_ADMIN=probe-admin:probe-admin-pw-1
//   VIDEO_STAFF=probe-staff:probe-staff-pw-1 VIDEO_WRITER=probe-writer:probe-writer-pw-1

const WEB = process.env.VIDEO_URL ?? process.env.PILLAR43_URL ?? 'http://127.0.0.1:5241'
const OUT = process.env.VIDEO_OUT ?? 'test-results/video'
const Q001 = 'Where are we allowed to sell the Lanterns book, and is it paperback only?'

type Who = { name: string; password: string }
function account(envName: string, fallback: Who): Who {
  const v = process.env[envName]
  if (!v) return fallback
  const i = v.indexOf(':')
  return { name: v.slice(0, i), password: v.slice(i + 1) }
}
const ADMIN = account('VIDEO_ADMIN', { name: 'Marguerite', password: 'video-admin-pass-1' })
const STAFF = account('VIDEO_STAFF', { name: 'Ines', password: 'video-ines-pass-1' })
const WRITER = account('VIDEO_WRITER', { name: 'Tomasz', password: 'video-writer-pass-1' })

test.use({
  baseURL: WEB,
  viewport: { width: 1440, height: 900 },
  colorScheme: 'dark',
  video: { mode: 'on', size: { width: 1440, height: 900 } },
})

const read = (page: Page, ms = 4000) => page.waitForTimeout(ms)

// The visible sign-in screen, typed at the same pace as the questions.
async function signIn(page: Page, who: Who) {
  await page.goto('/')
  const form = page.getByRole('form', { name: 'Sign in' })
  await expect(form).toBeVisible({ timeout: 30_000 })
  await form.getByLabel('Name').pressSequentially(who.name, { delay: 60 })
  await form.getByLabel('Password').pressSequentially(who.password, { delay: 60 })
  await read(page, 500)
  await form.getByRole('button', { name: 'Sign in' }).click()
  await expect(form).toBeHidden({ timeout: 30_000 })
}

async function signOut(page: Page) {
  await page.getByRole('button', { name: 'Sign out' }).click()
  await expect(page.getByRole('form', { name: 'Sign in' })).toBeVisible({ timeout: 20_000 })
}

async function openAsk(page: Page, who: Who) {
  await signIn(page, who)
  await expect(page.getByTestId('ask-view')).toBeVisible({ timeout: 30_000 })
}

async function ask(page: Page) {
  const box = page.getByLabel('Question')
  await box.click()
  await box.pressSequentially(Q001, { delay: 60 })
  await read(page, 1000)
  await page.getByTestId('ask-view').getByRole('button', { name: 'Ask', exact: true }).click()
  // The answer streams, so the response body is not parsed: the visible
  // Answer region is what the shot waits for.
  await expect(page.getByRole('region', { name: 'Answer' })).toBeVisible({ timeout: 150_000 })
}

const lanterns = (page: Page) => page.getByRole('row').filter({ hasText: 'Lanterns' })

// The writer's visible level control on "My work".
async function setLevel(page: Page, name: RegExp) {
  const radio = lanterns(page).getByRole('radio', { name })
  const done = page.waitForResponse((r) => r.url().includes('/api/archive/items/consent') && r.ok())
  await radio.click()
  await done
  await expect(radio).toBeChecked()
}

test.afterEach(async ({ page }, info) => {
  const n = info.title.match(/^shot (\w+):/)![1]
  const video = page.video()
  await page.close()
  if (info.status === 'skipped') return
  mkdirSync(OUT, { recursive: true })
  await video!.saveAs(`${OUT}/shot-${n}.webm`)
})

test('shot 1: sign in, the empty Ask view @video', async ({ page }) => {
  await openAsk(page, ADMIN)
  await read(page, 6000)
})

test('shot 2: type the question and ask @video', async ({ page }) => {
  await openAsk(page, ADMIN)
  await read(page, 1500)
  await ask(page)
  await expect(page.getByRole('button', { name: /^Source \d+$/ }).first()).toBeVisible({ timeout: 60_000 })
  await read(page, 3000)
})

test('shot 3: the answer and its citation @video', async ({ page }) => {
  await openAsk(page, ADMIN)
  await ask(page)
  await read(page, 4000)
  await page.getByRole('button', { name: /^Source \d+$/ }).first().click()
  await expect(page.getByRole('complementary', { name: 'Source' })).toBeVisible()
  await read(page, 7000)
})

test('shot 4: open the file at the cited page @video', async ({ page }) => {
  await openAsk(page, ADMIN)
  await ask(page)
  await page.getByRole('button', { name: /^Source \d+$/ }).first().click()
  const source = page.getByRole('complementary', { name: 'Source' })
  await read(page, 2500)
  await source.getByRole('button', { name: 'Open whole file' }).click()
  // The page is what the shot needs. The highlight on it is waited for softly:
  // the shot never fails on it.
  await expect(page.getByAltText(/^Page \d+$/).first()).toBeVisible({ timeout: 30_000 })
  await page.getByTestId('passage-highlight').first().waitFor({ timeout: 5000 }).catch(() => {})
  await read(page, 6000)
})

test('shot 5: the writer closes the Lanterns contract, staff re-ask and see it declined @video', async ({ page }) => {
  test.setTimeout(300_000)
  await signIn(page, WRITER)
  await expect(page.getByTestId('terms-view')).toBeVisible({ timeout: 30_000 })
  await expect(page.getByRole('button', { name: 'My work' })).toBeVisible()
  await expect(lanterns(page)).toHaveCount(1)
  await read(page, 5000)
  try {
    // Staff, not Private: Private hides the item from staff and the archive
    // only counts it; Staff lets the answer name it.
    await setLevel(page, /^Staff/)
    await read(page, 3000)
    await signOut(page)

    await signIn(page, STAFF)
    await expect(page.getByTestId('ask-view')).toBeVisible({ timeout: 30_000 })
    await ask(page)
    const answer = page.getByRole('region', { name: 'Answer' })
    await expect(answer).toContainText('It is closed by its writer, so the AI did not read it.', { timeout: 120_000 })
    const silences = page.getByTestId('silences')
    await silences.scrollIntoViewIfNeeded()
    await expect(silences).toContainText('Lanterns')
    await read(page, 9000)
  } finally {
    // Restore Model through the writer's visible control, whatever happened.
    const out = page.getByRole('button', { name: 'Sign out' })
    if (await out.isVisible().catch(() => false)) await signOut(page)
    await signIn(page, WRITER)
    await expect(page.getByTestId('terms-view')).toBeVisible({ timeout: 30_000 })
    await setLevel(page, /^Model/)
  }
})

test('shot 6: Explore yellow, then Cassia Merrowby\'s record @video', async ({ page }) => {
  await openAsk(page, STAFF)
  await page.getByRole('button', { name: 'Explore' }).first().click()
  const view = page.getByTestId('explore-view')
  await expect(view).toBeVisible()
  await read(page, 1500)
  const topic = view.getByLabel('Topic')
  await topic.click()
  await topic.pressSequentially('yellow', { delay: 60 })
  await read(page, 800)
  await view.getByRole('button', { name: 'Explore', exact: true }).click()
  const group = view.getByRole('group', { name: /Documents matching yellow/ })
  const dots = group.locator('button[data-dot]')
  await expect(dots.first()).toBeVisible({ timeout: 30_000 })
  await read(page, 4000)
  await dots.first().click()
  const passage = page.getByRole('complementary', { name: 'Passage' })
  await expect(passage.getByTestId('passage-text')).toContainText('yellow', { timeout: 30_000 })
  await read(page, 4500)

  await page.getByRole('button', { name: 'People' }).first().click()
  const people = page.getByTestId('people-view')
  await people.getByRole('list', { name: 'People' }).getByRole('button', { name: /Cassia Merrowby/ }).click()
  const record = people.getByRole('article', { name: 'Record: Cassia Merrowby' })
  await expect(record.getByRole('heading', { name: 'Cassia Merrowby' })).toBeVisible({ timeout: 20_000 })
  await expect(record.getByRole('list', { name: 'Titles' })).toContainText('The Salt Ledger')
  await expect(record.getByTestId('person-dates')).toBeVisible()
  const notOpen = record.getByTestId('not-open')
  await notOpen.scrollIntoViewIfNeeded()
  await expect(notOpen).toContainText(/Not open to the AI: [1-9]/)
  await read(page, 7000)
})

test('shot 7: the Files rail @video', async ({ page }) => {
  await openAsk(page, ADMIN)
  await page.getByRole('button', { name: 'Files' }).first().click()
  await read(page, 3000)
  for (const dir of ['contracts', 'letters']) {
    const row = page.getByText(dir, { exact: true }).first()
    if (await row.isVisible().catch(() => false)) await row.click()
    await read(page, 2500)
  }
  await read(page, 3000)
})
