import { expect, test } from '@playwright/test'
import { signInAs } from './archive-helpers'

// Settings answers 404 for a writer (org_gate), so the ribbon must not offer it.
// Accounts come from the CLI against your own stack, e.g.:
//   docker exec <project>-api-1 python scripts/archive_cli.py account p4-writer writer p4-writer-pw-1
//   docker exec <project>-api-1 python scripts/archive_cli.py owner p4-writer <an item path>
// Env: SETTINGS_ADMIN / SETTINGS_ADMIN_PW, SETTINGS_WRITER / SETTINGS_WRITER_PW.
const ADMIN = { name: process.env.SETTINGS_ADMIN ?? 'p4-admin', password: process.env.SETTINGS_ADMIN_PW ?? 'p4-admin-pw-1' }
const WRITER = { name: process.env.SETTINGS_WRITER ?? 'p4-writer', password: process.env.SETTINGS_WRITER_PW ?? 'p4-writer-pw-1' }

test('an admin sees Settings in the ribbon and it opens', async ({ page }) => {
  await signInAs(page, ADMIN)
  const settings = page.getByRole('button', { name: 'Settings' })
  await expect(settings).toBeVisible()
  await settings.click()
  await expect(page.getByRole('navigation', { name: 'Settings sections' })).toBeVisible()
})

test('a writer sees no Settings button, and ⌘, opens nothing', async ({ page }) => {
  await signInAs(page, WRITER)
  await expect(page.getByRole('button', { name: 'My work' })).toBeVisible({ timeout: 20_000 })
  await expect(page.getByRole('button', { name: 'Settings' })).toHaveCount(0)
  await page.keyboard.press('Control+,')
  await page.keyboard.press('Meta+,')
  await expect(page.getByRole('navigation', { name: 'Settings sections' })).toHaveCount(0)
})
