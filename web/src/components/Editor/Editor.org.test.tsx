/**
 * The Editor as the archive's file viewer: a cited PDF sentence shows as a
 * "Cited:" strip, scoped to the file it was cited in.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, act, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

const { apiMock } = vi.hoisted(() => ({
  apiMock: {
    readFile: vi.fn(),
    writeFile: vi.fn().mockResolvedValue({ ok: true }),
    annotationPath: vi.fn().mockResolvedValue({ annotation_path: 'notes/_annotations/x.md' }),
    fileActivity: vi.fn().mockResolvedValue({}),
    gitLog: vi.fn().mockResolvedValue({ commits: [] }),
    findFile: vi.fn().mockResolvedValue({ results: [] }),
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

describe('Editor — cited PDF', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiMock.readFile.mockResolvedValue({ path: 'library/a.md', content: '# A', ext: '.md', mount: 'library' })
  })

  it('PDF: a cited sentence shows as a "Cited:" strip only for the file it was cited in', async () => {
    apiMock.readFile.mockResolvedValue({ path: 'library/c.pdf', content: '', ext: '.pdf', mount: 'library', binary: true })
    act(() => {
      useAppStore.getState().setPdfTarget({ path: 'library/c.pdf', page: 2, text: 'The Translator shall receive 50%.' })
      useAppStore.getState().setCurrentFile('library/c.pdf')
    })
    const { unmount } = renderEditor()
    const strip = await screen.findByTestId('pdf-cited')
    expect(strip.textContent).toBe('Cited: The Translator shall receive 50%.')
    unmount()
    act(() => { useAppStore.getState().setPdfTarget({ path: 'library/other.pdf', page: 2, text: 'x' }) })
    renderEditor()
    await waitFor(() => expect(apiMock.readFile).toHaveBeenCalled())
    expect(screen.queryByTestId('pdf-cited')).toBeNull()
  })
})
