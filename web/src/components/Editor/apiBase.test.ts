/**
 * Guard: every fetch in the Editor must honour VITE_API_URL.
 *
 * `web/src/lib/api/_fetch.ts` exports BASE (= import.meta.env.VITE_API_URL ?? '')
 * and every call in lib/api/ prefixes it. Fetches in Editor/ once did not —
 * they hardcoded a root-relative '/api/...'.
 *
 * That works today only because something happens to proxy /api at the origin
 * serving the app: nginx in production (web/nginx.conf) and Vite's dev proxy
 * (vite.config.ts). It breaks the moment the frontend is served from anywhere
 * that isn't proxying to the API — which is exactly what VITE_API_URL exists to
 * express, and docker-compose.yml sets it to http://127.0.0.1:8002.
 *
 * These assertions read the source rather than executing the component: the
 * call sites sit inside render paths that would need a live page image to
 * reach. The invariant being protected is lexical anyway —
 * "this module routes its requests through BASE".
 */
import { describe, it, expect } from 'vitest'
// ?raw keeps this to Vite's own module graph — no node:fs, so it typechecks
// under the app tsconfig (which has no "node" types) exactly as it runs.
import pdfViewerSrc from './PDFViewer.tsx?raw'

const SOURCES: Record<string, string> = {
  'PDFViewer.tsx': pdfViewerSrc,
}

/** Every fetch( ... ) call's first argument, as written. */
function fetchTargets(src: string): string[] {
  return [...src.matchAll(/\bfetch\(\s*([^,)]+)/g)].map((m) => m[1].trim())
}

/**
 * Every template literal that builds an `/api/...` URL, as written.
 *
 * `fetchTargets` alone was not enough. PDFViewer builds its page URL into a
 * `pageUrl` const and hands it to an `<img src>` — never to `fetch` — so the
 * root-relative `/api/file/pdf-page` it hardcoded was invisible to this guard
 * for as long as the guard has existed. A request is a request whether the
 * browser makes it from `fetch` or from an element's `src`.
 */
function apiUrlLiterals(src: string): string[] {
  return [...src.matchAll(/`([^`]*\/api\/[^`]*)`/g)].map((m) => m[0])
}

describe('Editor fetches honour VITE_API_URL', () => {
  for (const [file, src] of Object.entries(SOURCES)) {
    it(`${file} does not hardcode a root-relative /api path`, () => {
      const targets = fetchTargets(src)
      expect(targets.length).toBeGreaterThan(0)
      for (const t of targets) {
        // A literal starting with '/api' means the origin is assumed.
        expect(t).not.toMatch(/^['"`]\/api/)
      }
    })

    it(`${file} imports BASE from the api layer`, () => {
      expect(src).toMatch(/import\s*\{[^}]*\bBASE\b[^}]*\}\s*from/)
    })

    it(`${file} builds every /api URL through BASE, not just its fetches`, () => {
      const urls = apiUrlLiterals(src)
      expect(urls.length).toBeGreaterThan(0)
      for (const u of urls) {
        // A template literal opening with `/api` assumes the app's origin
        // proxies the API. Consumed by <img src>, it fails silently.
        expect(u).not.toMatch(/^`\/api/)
      }
    })
  }
})
