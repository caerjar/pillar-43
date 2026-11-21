import { defineConfig, devices } from '@playwright/test'

// Runs against a running org stack (the archive compose project), not a
// dev server: Ask needs the API and the local model behind it. Point
// PILLAR43_URL at your own instance; never at someone else's running one.
// Locally, the installed Google Chrome; CI installs Playwright's Chromium.
const channel = process.env.CI ? undefined : 'chrome'

export default defineConfig({
  testDir: 'e2e',
  // A local 8B model answers in 10-35 s.
  timeout: 180_000,
  workers: 1,
  // Screen recordings for the video: run on purpose with VIDEO_RUN=1 --grep @video.
  grepInvert: process.env.VIDEO_RUN ? undefined : /@video/,
  use: { baseURL: process.env.PILLAR43_URL ?? 'http://127.0.0.1:5191/', trace: 'retain-on-failure' },
  projects: [{ name: 'desktop', use: { ...devices['Desktop Chrome'], channel, viewport: { width: 1440, height: 900 } } }],
})
