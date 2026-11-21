/**
 * Regression guard — an oversized file must never reach the editor.
 *
 * `read_file` declines to send a body over MAX_EDITOR_BYTES, but it does so
 * with `binary: false` and a null `content`. Every consumer branched on
 * `binary` alone, and `too_large` appeared nowhere in the frontend, so the
 * file fell through to the normal path: `draft` was seeded to '', CodeMirror
 * mounted empty over a real file, and the 700ms autosave wrote that emptiness
 * back. Silent, and it targeted the largest files in the vault.
 *
 * What this pins is the observable consequence, not the field name: no edit
 * affordance, no CodeMirror, and no write. A future refactor that keeps
 * reading `too_large` but stops guarding the render still fails here.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, act, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

const FILE = 'notes/huge.md'

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

vi.mock('@uiw/react-codemirror', async () => {
  const { forwardRef } = await import('react')
  return {
    default: forwardRef<HTMLTextAreaElement, { value: string; onChange?: (v: string) => void }>(
      ({ value, onChange }, ref) => (
        <textarea ref={ref} data-testid="cm" value={value} onChange={(e) => onChange?.(e.target.value)} />
      ),
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

describe('Editor — oversized file is never editable', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // Exactly what the backend sends: binary FALSE, content null.
    apiMock.readFile.mockResolvedValue({
      path: FILE,
      content: null,
      binary: false,
      ext: '.md',
      too_large: true,
      size_mb: 4.2,
      message: 'File too large for editor (4.2 MB). Maximum size: 2 MB',
    })
    act(() => { useAppStore.getState().setCurrentFile(FILE) })
  })

  it('shows the size notice instead of an editor', async () => {
    renderEditor()
    const notice = await screen.findByTestId('editor-too-large')
    expect(notice).toBeTruthy()
    expect(notice.textContent).toContain('4.2 MB')
  })

  it('offers no way to start editing', async () => {
    renderEditor()
    await screen.findByTestId('editor-too-large')
    // The Edit button is the only entry to CodeMirror. Its absence is what
    // makes truncation unreachable rather than merely unlikely.
    expect(screen.queryByRole('button', { name: 'Edit' })).toBeNull()
    expect(screen.queryByTestId('cm')).toBeNull()
  })

  it('never writes to the file', async () => {
    renderEditor()
    await screen.findByTestId('editor-too-large')
    await waitFor(() => expect(apiMock.readFile).toHaveBeenCalled())
    expect(apiMock.writeFile).not.toHaveBeenCalled()
  })
})
