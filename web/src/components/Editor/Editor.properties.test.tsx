/**
 * A note's frontmatter stays out of the rendered body.
 *
 * `marked` turned the opening `---` into a horizontal rule and the keys into
 * one run-on paragraph, so every note carrying metadata opened with a slab of
 * visible noise. Nothing errored — it just looked wrong, in a way that reads
 * as "this app does not understand my files".
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, act } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

const FILE = 'notes/with-properties.md'

const WITH_FRONTMATTER = [
  '---',
  'session_id: e311ea18',
  'date: 2026-08-08',
  'tags: [herbs, grief]',
  '---',
  '',
  '# The actual note',
  '',
  'Body text.',
].join('\n')

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

describe('Editor — frontmatter', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    act(() => { useAppStore.getState().setCurrentFile(FILE) })
  })

  it('keeps the raw fence out of the rendered body', async () => {
    apiMock.readFile.mockResolvedValue({
      path: FILE, content: WITH_FRONTMATTER, ext: '.md', mount: 'notes',
    })
    const { container } = renderEditor()
    await screen.findByText('The actual note')

    const prose = container.querySelector('.prose')!
    // The body renders; the frontmatter keys no longer appear inside it as
    // paragraph text, and the fence no longer becomes an <hr>.
    expect(prose.textContent).toContain('The actual note')
    expect(prose.textContent).not.toContain('session_id: e311ea18')
    expect(prose.querySelector('hr')).toBeNull()
  })

  it('renders a note without frontmatter unchanged', async () => {
    apiMock.readFile.mockResolvedValue({
      path: FILE, content: '# Plain\n\nNo metadata here.\n', ext: '.md', mount: 'notes',
    })
    const { container } = renderEditor()

    await screen.findByText('Plain')
    expect(container.querySelector('.prose')!.textContent).toContain('No metadata here.')
  })

  it('does not treat a horizontal rule as frontmatter', async () => {
    // `---` mid-note is a rule. Reading it as frontmatter would eat the top of
    // the note.
    apiMock.readFile.mockResolvedValue({
      path: FILE, content: '# Title\n\nIntro.\n\n---\n\nAfter.\n', ext: '.md', mount: 'notes',
    })
    const { container } = renderEditor()

    await screen.findByText('Title')
    expect(container.querySelector('.prose')!.textContent).toContain('Intro.')
    expect(container.querySelector('.prose')!.textContent).toContain('After.')
  })

  it('still shows the raw frontmatter in edit mode', async () => {
    // That is where you change it. Hiding it there would make it uneditable.
    apiMock.readFile.mockResolvedValue({
      path: FILE, content: WITH_FRONTMATTER, ext: '.md', mount: 'notes',
    })
    renderEditor()

    const editBtn = await screen.findByRole('button', { name: 'Edit' })
    act(() => { editBtn.click() })

    const cm = await screen.findByTestId('cm')
    expect((cm as HTMLTextAreaElement).value).toContain('session_id: e311ea18')
  })
})
