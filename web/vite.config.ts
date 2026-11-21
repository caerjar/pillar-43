import { defineConfig } from 'vite'
import { execSync } from 'node:child_process'
import react from '@vitejs/plugin-react'

// Build stamp: prefer build-time env (set via Docker ARG), then fall back to
// `git rev-parse` (works for local `vite build`/`vite preview` outside Docker).
function resolveSha(): string {
  if (process.env.PILLAR43_GIT_SHA) return process.env.PILLAR43_GIT_SHA
  try {
    return execSync('git rev-parse --short HEAD', { stdio: ['ignore', 'pipe', 'ignore'] })
      .toString()
      .trim()
  } catch {
    return 'unknown'
  }
}
const PILLAR43_SHA = resolveSha()
const PILLAR43_BUILT_AT = process.env.PILLAR43_BUILT_AT || new Date().toISOString()

export default defineConfig({
  define: {
    __PILLAR43_SHA__: JSON.stringify(PILLAR43_SHA),
    __PILLAR43_BUILT_AT__: JSON.stringify(PILLAR43_BUILT_AT),
  },
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    // Needed by src/design-tokens.test.ts, which reads the stylesheets with
    // `import.meta.glob(..., '?raw')` to check that every var(--token) is
    // actually declared. With CSS handling off (the vitest default) those
    // imports resolve to empty strings and the guard silently reports every
    // token in the app as missing. Nothing else in the suite asserts on CSS.
    css: true,
    setupFiles: ['./src/test-setup.ts'],
    // e2e/ holds Playwright specs, run by `npx playwright test` against a
    // live stack; vitest must not collect them.
    include: ['src/**/*.test.{ts,tsx}'],
    coverage: {
      provider: 'v8',
      reporter: ['text-summary', 'json-summary', 'html'],
      // Measure hand-written source only. Including _generated.ts (7.4k lines
      // of codegen that is a type declaration file at runtime, so never
      // executed) drags the number down by ~20 points while saying nothing
      // about how well the app is tested.
      include: ['src/**/*.{ts,tsx}'],
      exclude: [
        'src/lib/api/_generated.ts',
        'src/**/*.test.{ts,tsx}',
        'src/test-setup.ts',
        'src/main.tsx',
        'src/vite-env.d.ts',
      ],
      // Thresholds are the MEASURED floor rounded down, not a target. Their
      // job is to stop coverage sliding backwards; raising them is a
      // deliberate act after writing tests, not an aspiration set here and
      // ignored.
      //   2026-08-05: 51.48 / 67.87 / 36.51 / 51.48
      //   2026-08-06: 52.73 / --    / 37.44 / 52.73
      //     (useSSEStream and RecentPanel off 0%)
      //   2026-08-07: 56.85 / 70.62 / 38.39 / 56.85
      //     (HistoryPanel, Transcribe, GraphView + its filter pipeline
      //      off 0%; the branch jump is mostly filterGraph's six stages)
      thresholds: {
        statements: 56,
        branches: 70,
        functions: 38,
        lines: 56,
      },
    },
  },
  server: {
    port: 5173,
    host: true,
    proxy: {
      '/api': {
        // API_PROXY_TARGET lets a dev server on the host point at a stack's
        // published api port; the default is the compose service name.
        target: process.env.API_PROXY_TARGET || 'http://api:8000',
        changeOrigin: true,
      },
    },
  },
  preview: {
    port: 5173,
    host: true,
    proxy: {
      '/api': {
        target: 'http://api:8000',
        changeOrigin: true,
      },
    },
  },
})
