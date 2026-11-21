/**
 * Every `var(--token)` referenced anywhere in src/ must actually be declared.
 *
 * This exists because the failure mode is silent. A token that was never
 * declared makes `var(--bg-secondary)` resolve to nothing, so the property
 * falls back to its initial value — a background renders transparent, a colour
 * falls through to whatever it inherits — and nothing errors. tsc cannot see
 * inside a string; ESLint's no-restricted-syntax only bans hex literals and is
 * perfectly happy with a token that does not exist; no unit test asserts on
 * computed colour. Moving 28 hex literals onto tokens is exactly the change
 * that would introduce one of these, which is why the guard landed with it.
 *
 * It immediately found 12: SettingsPanel.css and ThreadMap.tsx were reaching
 * for a whole parallel vocabulary (`--bg-primary`, `--bg-secondary`,
 * `--surface-2`, `--danger`, `--text`) that this project never declared. Ten of
 * those were `background:`, which is to say they were rendering transparent.
 *
 * The both-themes half matters independently: a token declared only in the dark
 * `:root` block leaves light mode falling back to initial, which is how you get
 * a component that looks right in the theme you developed in and broken in the
 * other one.
 *
 * Files are pulled in with `import.meta.glob(..., '?raw')` rather than fs so
 * the suite needs no @types/node — vite/client already types this — and so a
 * NEW stylesheet is picked up automatically instead of having to be added to a
 * list here.
 */
import { describe, it, expect } from 'vitest'

const CSS_FILES = import.meta.glob('./**/*.css', {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>

const SOURCE_FILES = import.meta.glob('./**/*.{ts,tsx,css}', {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>

/**
 * Tokens are declared across more than one stylesheet: the `--eon-*` palette
 * and the motion/shadow scales live in design-tokens.css, which index.css
 * imports, while the semantic aliases (--accent, --error, --text-primary) are
 * in index.css itself. An earlier version of this test read only index.css and
 * duly reported the entire --eon-* family as missing — the family the ESLint
 * rule's own message tells you to use.
 */
const ALL_CSS = Object.values(CSS_FILES).join('\n')

/**
 * Tailwind's Preflight — vendored into index.css when Tailwind itself was
 * removed — parameterises its font stacks through these and ships them with the
 * full fallback list inline, precisely so they work undeclared. Preflight's
 * contract, not ours.
 */
const NOT_OURS = new Set(['--default-font-family', '--default-mono-font-family'])

/**
 * Custom properties declared in a block of CSS. Scanning for `--name:` rather
 * than parsing properly is enough here: the theme blocks are flat lists of
 * declarations.
 */
function declaredIn(block: string): Set<string> {
  return new Set([...block.matchAll(/(--[\w-]+)\s*:/g)].map((m) => m[1]))
}

/**
 * Tokens referenced as `var(--x)` or `var(--x, fallback)`. The `[),]` anchor is
 * load-bearing: without it `var\(\s*--text` also matches `var(--text-primary`,
 * which is how a first pass at this test reported 143 phantom failures.
 */
function referencedIn(text: string): Set<string> {
  return new Set(
    [...text.matchAll(/var\(\s*(--[\w-]+)\s*[),]/g)].map((m) => m[1]),
  )
}

describe('design tokens', () => {
  const declared = declaredIn(ALL_CSS)

  it('declares every token that src/ references', () => {
    const missing: string[] = []
    for (const [path, text] of Object.entries(SOURCE_FILES)) {
      if (/\.test\.tsx?$/.test(path)) continue
      for (const token of referencedIn(text)) {
        if (!declared.has(token) && !NOT_OURS.has(token)) {
          missing.push(`${path}: ${token}`)
        }
      }
    }
    expect(missing).toEqual([])
  })

  it('declares the theme-reactive tokens in both light and dark', () => {
    const css = CSS_FILES['./index.css']
    expect(css, 'index.css not found by the glob').toBeTruthy()

    // The light theme is an override block appended after the dark `:root`, so
    // splitting on its selector gives the two palettes.
    const start = css.indexOf('[data-theme="light"]')
    expect(start, 'light-theme override block not found').toBeGreaterThan(-1)

    const dark = declaredIn(css.slice(0, start))
    const light = declaredIn(css.slice(start))

    // --on-accent was added for the 16 call sites that hardcoded #fff on an
    // accent background. It has to exist in both themes or half of them
    // silently lose their foreground colour.
    for (const token of [
      '--on-accent',
      '--accent',
      '--error',
      '--success',
      '--warning',
    ]) {
      expect(dark.has(token), `${token} missing from dark theme`).toBe(true)
      expect(light.has(token), `${token} missing from light theme`).toBe(true)
    }
  })
})
