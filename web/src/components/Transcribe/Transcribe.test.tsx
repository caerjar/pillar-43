/**
 * Transcribe had zero coverage. What is worth pinning is not the recorder
 * plumbing (that is the browser's) but the places where dictated text can be
 * silently lost or filed somewhere the user did not intend:
 *
 *  - final results must APPEND, not replace, or a long dictation keeps only
 *    the last utterance
 *  - the Route-to-Inbox toggle must move the save path, since that is the
 *    difference between a note the inbox processor classifies and one that
 *    sits in transcripts/ unseen
 *  - a trailing "/" must grow a filename, or writeFile is called with a
 *    directory
 *  - a failed save must NOT clear the transcript — the text is unrecoverable
 *
 * `../../lib/speech` is mocked per the precedent in TaskBoard.test.tsx, with
 * `speechRecognitionSupported` behind a getter so the unsupported-browser
 * branch can be exercised in the same file.
 *
 * The scrollIntoView shim is required, not defensive: Transcribe's auto-scroll
 * effect optional-chains the REF (`bottomRef.current?.scrollIntoView(...)`),
 * not the method, so once a real div mounts jsdom throws on a function it does
 * not implement.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { RecognitionCallbacks } from '../../lib/speech'
import { Transcribe } from './Transcribe'

let supported = true
let captured: RecognitionCallbacks | null = null
const mockStart = vi.fn()
const mockStop = vi.fn()

vi.mock('../../lib/speech', () => ({
  get speechRecognitionSupported() {
    return supported
  },
  createContinuous: (cb: RecognitionCallbacks) => {
    captured = cb
    return { start: mockStart, stop: mockStop }
  },
}))

const mockSetCurrentFile = vi.fn()
vi.mock('../../stores/appStore', () => ({
  useAppStore: (selector: (s: unknown) => unknown) => {
    const store = { setCurrentFile: mockSetCurrentFile }
    return selector ? selector(store) : store
  },
}))

const mockWriteFile = vi.fn()
vi.mock('../../lib/api', () => ({
  api: {
    appSettings: () => Promise.resolve({ voice_language: '' }),
    writeFile: (...a: unknown[]) => mockWriteFile(...a),
  },
}))

beforeEach(() => {
  supported = true
  captured = null
  mockStart.mockReset()
  mockStop.mockReset()
  mockSetCurrentFile.mockReset()
  mockWriteFile.mockReset().mockResolvedValue({})
  Element.prototype.scrollIntoView = vi.fn()
})

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const utils = render(
    <QueryClientProvider client={qc}>
      <Transcribe />
    </QueryClientProvider>,
  )
  return { ...utils, qc }
}

/** Start recording and feed in one committed utterance. */
async function dictate(...utterances: string[]) {
  fireEvent.click(screen.getByRole('button', { name: /start/i }))
  for (const u of utterances) {
    await act(async () => {
      captured!.onFinal(u)
    })
  }
}

describe('Transcribe browser support', () => {
  it('explains itself on a browser without speech recognition', () => {
    supported = false
    wrap()
    expect(screen.getByText(/not supported in this browser/i)).toBeInTheDocument()
    // and offers a way forward rather than just failing
    expect(screen.getByText(/chrome, edge, or safari/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /start/i })).not.toBeInTheDocument()
  })
})

describe('Transcribe recording', () => {
  it('prompts before anything has been dictated', () => {
    wrap()
    expect(screen.getByText(/press start to begin dictating/i)).toBeInTheDocument()
  })

  it('accumulates successive final results instead of replacing them', async () => {
    wrap()
    await dictate('first thought', 'second thought')
    expect(screen.getByText(/first thought second thought/)).toBeInTheDocument()
  })

  it('shows interim text while the engine is still deciding', async () => {
    wrap()
    fireEvent.click(screen.getByRole('button', { name: /start/i }))
    await act(async () => {
      captured!.onInterim('half a sen')
    })
    expect(screen.getByText('half a sen')).toBeInTheDocument()
  })

  it('moves through listening → paused → listening', async () => {
    wrap()
    fireEvent.click(screen.getByRole('button', { name: /start/i }))
    expect(screen.getByText('LIVE')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /pause/i }))
    // The badge specifically — /paused/i alone also matches the placeholder
    // copy ("Paused. Press Resume to continue.") in the transcript area.
    expect(screen.getByText('⏸ PAUSED')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /resume/i }))
    expect(screen.getByText('LIVE')).toBeInTheDocument()
  })

  it('ignores no-speech but surfaces a real mic error', async () => {
    wrap()
    fireEvent.click(screen.getByRole('button', { name: /start/i }))

    // Silence is normal during dictation; reporting it would make the panel
    // cry wolf every time the user paused to think.
    await act(async () => {
      captured!.onError('no-speech')
    })
    expect(screen.queryByText(/mic error/i)).not.toBeInTheDocument()

    await act(async () => {
      captured!.onError('not-allowed')
    })
    expect(screen.getByText(/mic error: not-allowed/i)).toBeInTheDocument()
  })
})

describe('Transcribe saving', () => {
  it('keeps the transcript when the save fails', async () => {
    // The text exists nowhere else. Clearing on failure loses it outright.
    mockWriteFile.mockRejectedValue(new Error('disk full'))
    wrap()
    await dictate('irreplaceable')
    fireEvent.click(screen.getByRole('button', { name: /save to file/i }))

    expect(await screen.findByText(/save failed: disk full/i)).toBeInTheDocument()
    expect(screen.getByText(/irreplaceable/)).toBeInTheDocument()
  })

  it('appends a filename when the path is a directory', async () => {
    wrap()
    await dictate('dictated body')
    fireEvent.click(screen.getByRole('button', { name: /save to file/i }))

    await waitFor(() => expect(mockWriteFile).toHaveBeenCalled())
    const [path, body] = mockWriteFile.mock.calls[0]
    expect(path).toMatch(/^notes\/transcripts\/\d{4}-\d{2}-\d{2}-\d{6}\.md$/)
    expect(body).toContain('dictated body')
    expect(body).toMatch(/^# Transcript — /)
  })

  it('respects a path the user typed in full', async () => {
    wrap()
    await dictate('body')
    fireEvent.change(screen.getByPlaceholderText(/notes\/transcripts\/note\.md/), {
      target: { value: 'notes/meeting.md' },
    })
    fireEvent.click(screen.getByRole('button', { name: /save to file/i }))

    await waitFor(() => expect(mockWriteFile.mock.calls[0][0]).toBe('notes/meeting.md'))
  })

  it('opens the saved file and refreshes the tree', async () => {
    wrap()
    await dictate('body')
    fireEvent.click(screen.getByRole('button', { name: /save to file/i }))

    await waitFor(() => expect(mockSetCurrentFile).toHaveBeenCalled())
    expect(mockSetCurrentFile.mock.calls[0][0]).toMatch(/^notes\/transcripts\//)
  })

  it('routes to the inbox when the toggle is on', async () => {
    // This is the whole point of the toggle: inbox/ gets classified and
    // thread-suggested, transcripts/ does not. Landing in the wrong one means
    // the note is never triaged.
    wrap()
    await dictate('classify me')
    fireEvent.click(screen.getByRole('checkbox'))

    expect(screen.getByRole('button', { name: /save to inbox/i })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /save to inbox/i }))

    await waitFor(() => expect(mockWriteFile).toHaveBeenCalled())
    expect(mockWriteFile.mock.calls[0][0]).toMatch(/^notes\/inbox\//)
  })

  it('returns the default path when the toggle goes back off', async () => {
    wrap()
    await dictate('body')
    const toggle = screen.getByRole('checkbox')
    fireEvent.click(toggle)
    fireEvent.click(toggle)

    fireEvent.click(screen.getByRole('button', { name: /save to file/i }))
    await waitFor(() => expect(mockWriteFile).toHaveBeenCalled())
    expect(mockWriteFile.mock.calls[0][0]).toMatch(/^notes\/transcripts\//)
  })

  it('offers no save controls until there is something to save', () => {
    wrap()
    expect(screen.queryByRole('button', { name: /save to file/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
  })

  it('discards the transcript on Clear and stops the recogniser', async () => {
    wrap()
    await dictate('never mind')
    fireEvent.click(screen.getByRole('button', { name: /clear/i }))

    expect(screen.getByText(/press start to begin dictating/i)).toBeInTheDocument()
    expect(mockStop).toHaveBeenCalled()
  })
})
