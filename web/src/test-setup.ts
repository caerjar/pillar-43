import '@testing-library/jest-dom'
import { vi } from 'vitest'

// jsdom's Storage implementation is sometimes attached to `window` but not
// to the bare `globalThis.localStorage` reference Zustand's persist middleware
// reads. When that happens, calls like `localStorage.clear()` from inside test
// helpers throw "clear is not a function" and Zustand-persisted stores fail
// to hydrate during render. Shim a minimal in-memory Storage if either is
// missing — idempotent: a real Storage with the right API is left alone.
function ensureStorage(target: 'localStorage' | 'sessionStorage') {
  const existing = (globalThis as unknown as Record<string, unknown>)[target] as Storage | undefined
  if (existing && typeof existing.clear === 'function' && typeof existing.setItem === 'function') return
  const store = new Map<string, string>()
  const shim: Storage = {
    getItem: (key) => (store.has(key) ? store.get(key)! : null),
    setItem: (key, value) => { store.set(key, String(value)) },
    removeItem: (key) => { store.delete(key) },
    clear: () => { store.clear() },
    key: (i) => Array.from(store.keys())[i] ?? null,
    get length() { return store.size },
  }
  Object.defineProperty(globalThis, target, { value: shim, writable: true, configurable: true })
  if (typeof window !== 'undefined') {
    Object.defineProperty(window, target, { value: shim, writable: true, configurable: true })
  }
}
ensureStorage('localStorage')
ensureStorage('sessionStorage')

// vitest runs in Node — provide require so inline mock factories compile cleanly

declare const require: (id: string) => any

// Framer Motion renders motion.div with initial styles (width: 0) in jsdom
// which hides content. Replace with plain divs for unit tests.
vi.mock('framer-motion', () => ({
  motion: {
    div: ({ children, style, ...props }: React.HTMLAttributes<HTMLDivElement> & { children?: React.ReactNode }) =>

      require('react').createElement('div', { style, ...props }, children),
  },
  AnimatePresence: ({ children }: { children?: React.ReactNode }) =>

    require('react').createElement(require('react').Fragment, null, children),
}))
