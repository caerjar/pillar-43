/**
 * Regression guard for the Editor freeze — "cleanup-fires-flush".
 *
 * the maintainer notes records this bug recurring THREE times, and Editor.tsx has
 * carried no test coverage (2026-07-30 audit). The shape:
 *
 *   const flush = useCallback(..., [saveMutation])   // unstable: useMutation
 *   useEffect(() => () => flush(), [currentFile, flush])  // cleanup every render
 *
 * `saveMutation` is a fresh object each render, so `flush` changed identity
 * every render, so the file-change effect tore down and re-ran its cleanup —
 * and that cleanup IS flush(). Result: one save request per keystroke, and the
 * editor grinds.
 *
 * What this test pins is the observable consequence, not the implementation:
 * typing N characters must produce ZERO writes until the 700ms debounce
 * elapses, then exactly one. Any reintroduction of an unstable `flush` fails
 * the first assertion.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, act, waitFor } from '@testing-library/react'
import { fireEvent } from '@testing-library/dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

const FILE = 'notes/freeze-test.md'

const { apiMock } = vi.hoisted(() => ({
  apiMock: {
    readFile: vi.fn(),
    writeFile: vi.fn().mockResolvedValue({ ok: true }),
    annotationPath: vi.fn().mockResolvedValue({ annotation_path: 'notes/_annotations/x.md' }),
    fileActivity: vi.fn().mockResolvedValue({}),
    gitLog: vi.fn().mockResolvedValue({ commits: [] }),
  },
}))

vi.mock('../../lib/api', () => ({ api: apiMock }))

// CodeMirror can't render meaningfully in jsdom — swap in a textarea that
// drives the same onChange contract the real editor uses.
vi.mock('@uiw/react-codemirror', async () => {
  const { forwardRef } = await import('react')
  return {
    // forwardRef because Editor attaches cmRef — a plain function component
    // warns and drops the ref.
    default: forwardRef<HTMLTextAreaElement, { value: string; onChange?: (v: string) => void }>(
      ({ value, onChange }, ref) => (
        <textarea ref={ref} data-testid="cm" value={value} onChange={(e) => onChange?.(e.target.value)} />
      ),
    ),
  }
})

// Heavy or irrelevant children — stubbed so the test isolates the save path.
vi.mock('../../lib/speech', () => ({
  // `speechSynthesisSupported` is a boolean value, and `loadVoices(cb)` returns
  // an unsubscribe function that Editor returns straight out of a useEffect —
  // mock either shape wrong and React calls a non-function as the destructor.
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

describe('Editor — save debounce (freeze regression)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiMock.readFile.mockResolvedValue({
      path: FILE, content: 'hello', ext: '.md', mount: 'notes',
    })
    act(() => { useAppStore.getState().setCurrentFile(FILE) })
  })

  it('does not write once per keystroke, then writes exactly once after the debounce', async () => {
    renderEditor()

    // Enter edit mode (CodeMirror only mounts there).
    const editBtn = await screen.findByRole('button', { name: 'Edit' })
    act(() => { editBtn.click() })

    const cm = await screen.findByTestId('cm')

    vi.useFakeTimers()
    try {
      // Five keystrokes in quick succession.
      for (const text of ['hello a', 'hello ab', 'hello abc', 'hello abcd', 'hello abcde']) {
        fireEvent.change(cm, { target: { value: text } })
      }

      // THE ASSERTION THAT CATCHES THE BUG. With an unstable `flush`, the
      // file-change effect's cleanup fired on each of these renders and this
      // count would be ~5 instead of 0.
      expect(apiMock.writeFile).not.toHaveBeenCalled()

      await act(async () => { vi.advanceTimersByTime(700) })
    } finally {
      vi.useRealTimers()
    }

    await waitFor(() => expect(apiMock.writeFile).toHaveBeenCalledTimes(1))
    expect(apiMock.writeFile).toHaveBeenCalledWith(FILE, 'hello abcde')
  })

  it('flushes pending edits when the open file changes, so keystrokes are not dropped', async () => {
    renderEditor()
    const editBtn = await screen.findByRole('button', { name: 'Edit' })
    act(() => { editBtn.click() })
    const cm = await screen.findByTestId('cm')

    fireEvent.change(cm, { target: { value: 'unsaved edit' } })
    expect(apiMock.writeFile).not.toHaveBeenCalled()

    // Navigate away before the debounce elapses.
    await act(async () => { useAppStore.getState().setCurrentFile('notes/other.md') })

    await waitFor(() => expect(apiMock.writeFile).toHaveBeenCalledWith(FILE, 'unsaved edit'))
  })
})
