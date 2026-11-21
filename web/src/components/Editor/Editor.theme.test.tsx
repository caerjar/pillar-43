/**
 * The editor must follow the app's light/dark setting.
 *
 * It was pinned to `oneDark` (Editor.tsx) regardless of theme, so turning on
 * light mode left a dark slab in the centre of an otherwise light app — in the
 * one pane you look at most. Nothing errored; it just looked broken.
 *
 * Asserted on the prop CodeMirror actually receives rather than on rendered
 * colours: CodeMirror cannot render meaningfully in jsdom (see
 * Editor.freeze.test.tsx), so a colour assertion here would be pretending to
 * know what was painted.
 *
 * The second test is the more important one. `theme` has the same stability
 * requirement as `extensions` — a fresh reference each render reconfigures
 * CodeMirror on every render, which is the freeze this file's sibling exists
 * to guard. Both branches must therefore be constants, not built inline.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, act } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { oneDark } from '@codemirror/theme-one-dark'

/** Last recorded value. `.at(-1)` is not in this project's TS lib target. */
const last = <T,>(xs: T[]): T => xs[xs.length - 1]

const FILE = 'notes/theme-test.md'

const { apiMock, themeProps } = vi.hoisted(() => ({
  apiMock: {
    readFile: vi.fn(),
    writeFile: vi.fn().mockResolvedValue({ ok: true }),
    annotationPath: vi.fn().mockResolvedValue({ annotation_path: 'notes/_annotations/x.md' }),
    fileActivity: vi.fn().mockResolvedValue({}),
    gitLog: vi.fn().mockResolvedValue({ commits: [] }),
  },
  // Every `theme` value CodeMirror was handed, in render order.
  themeProps: [] as unknown[],
}))

vi.mock('../../lib/api', () => ({ api: apiMock }))

vi.mock('@uiw/react-codemirror', async () => {
  const { forwardRef } = await import('react')
  return {
    default: forwardRef<HTMLTextAreaElement, { value: string; theme?: unknown; onChange?: (v: string) => void }>(
      ({ value, theme, onChange }, ref) => {
        themeProps.push(theme)
        return <textarea ref={ref} data-testid="cm" value={value} onChange={(e) => onChange?.(e.target.value)} />
      },
    ),
  }
})

vi.mock('../../lib/speech', () => ({
  speechSynthesisSupported: false,
  speak: vi.fn(),
  loadVoices: vi.fn(() => () => {}),
}))

import { Editor } from './Editor'
import { useAppStore } from '../../stores/appStore'

function renderEditor() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <Editor />
    </QueryClientProvider>,
  )
}

/** CodeMirror only mounts in edit mode. */
async function enterEditMode() {
  const editBtn = await screen.findByRole('button', { name: 'Edit' })
  act(() => { editBtn.click() })
  await screen.findByTestId('cm')
}

describe('Editor — follows the app theme', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    themeProps.length = 0
    apiMock.readFile.mockResolvedValue({
      path: FILE, content: 'hello', ext: '.md', mount: 'notes',
    })
    act(() => { useAppStore.getState().setCurrentFile(FILE) })
  })

  it('uses the dark theme when the app is dark', async () => {
    act(() => { useAppStore.getState().setLightMode(false) })
    renderEditor()
    await enterEditMode()
    expect(last(themeProps)).toBe(oneDark)
  })

  it('does NOT use the dark theme when the app is light', async () => {
    act(() => { useAppStore.getState().setLightMode(true) })
    renderEditor()
    await enterEditMode()
    expect(last(themeProps)).not.toBe(oneDark)
    expect(last(themeProps)).toBe('light')
  })

  it('keeps the theme reference stable across re-renders', async () => {
    // The freeze invariant, applied to `theme`. An inline-built value would
    // give a new reference on every render and reconfigure CodeMirror each
    // time — the exact shape Editor.freeze.test.tsx guards for `extensions`.
    act(() => { useAppStore.getState().setLightMode(false) })
    renderEditor()
    await enterEditMode()

    const before = themeProps.length
    // Any unrelated store write re-renders the Editor.
    act(() => { useAppStore.getState().setPendingLine(3) })
    expect(themeProps.length).toBeGreaterThan(before)

    const seen = new Set(themeProps)
    expect(seen.size, `theme identity changed across renders: ${seen.size} distinct values`).toBe(1)
  })
})
