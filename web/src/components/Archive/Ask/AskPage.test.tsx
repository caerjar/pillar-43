import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, within, waitFor, fireEvent, act, cleanup } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AskPage } from './AskPage'
import { useAskStore } from '../../../stores/askStore'
import { useAppStore } from '../../../stores/appStore'
import type { AskResponse } from '../../../lib/api/archive'

const CLAUSE = 'The Translator shall receive 50% of all subsidiary rights income.'

function response(over: Partial<AskResponse> = {}): AskResponse {
  return {
    question: 'Who gets subsidiary rights income on Weather for Ferrymen?',
    answer: [
      { text: 'The translator receives half.', cites: [1], quote: { passage: 1, sentence: 2, text: CLAUSE } },
      { text: 'The estate consented in May.', cites: [2, 1], quote: null },
    ],
    not_answered: false,
    would_answer: null,
    passages: [
      {
        n: 1, path: 'notes/contracts/ferrymen.pdf', title: 'Weather for Ferrymen contract', kind: 'contract',
        chunk_id: 'c1', ordinal: 0, heading: null,
        sentences: ['This agreement is made in 2020.', CLAUSE, 'It ends on notice.'],
      },
      {
        n: 2, path: 'notes/letters/estate.txt', title: 'Estate consent letter', kind: 'letter',
        chunk_id: 'c2', ordinal: 3, heading: null, sentences: ['We consent.'],
      },
    ],
    staff_only_sources: [{ path: 'notes/board/minutes.md', title: 'Board minutes September', kind: 'minutes' }],
    withheld_from_ai: 3,
    model: 'local', timing: { retrieve_s: 0.1, model_s: 9 },
    ...over,
  }
}

const OPEN = { total: 12, by_kind: [{ kind: 'contract', count: 6 }, { kind: 'letter', count: 1 }] }

function stubAsk(body: unknown, status = 200) {
  const f = vi.fn(async (url: string) => {
    if (String(url).includes('open-to-ai')) return new Response(JSON.stringify(OPEN), { status: 200 })
    if (String(url).includes('passage-boxes')) return new Response(JSON.stringify({ page: 1, match: 'none', boxes: [] }), { status: 200 })
    return new Response(JSON.stringify(body), { status })
  })
  vi.stubGlobal('fetch', f)
  return f
}

async function ask(q = 'Who gets subsidiary rights income?') {
  const user = userEvent.setup()
  await user.type(screen.getByLabelText('Question'), q)
  await user.click(screen.getByRole('button', { name: 'Ask' }))
  return user
}

describe('AskPage', () => {
  beforeEach(() => {
    useAskStore.setState({ history: [], activeIndex: null, pending: null, error: null })
    useAppStore.setState({ currentFile: null, leftTab: 'ask' })
  })
  afterEach(() => { vi.unstubAllGlobals() })

  it('posts the question and renders sentences, chips, the quote, withheld count and staff-only list', async () => {
    const f = stubAsk(response())
    render(<AskPage />)
    await ask()
    const answer = await screen.findByRole('region', { name: 'Answer' })
    expect(f).toHaveBeenCalledWith('/api/archive/ask', expect.objectContaining({ method: 'POST', body: JSON.stringify({ question: 'Who gets subsidiary rights income?' }) }))
    expect(within(answer).getByText(/The translator receives half\./)).toBeDefined()
    expect(within(answer).getAllByLabelText(/^Source \d$/).map((b) => b.textContent)).toEqual(['[1]', '[2]', '[1]'])
    // The quote is the backend's text, shown in a block quote with its source.
    const bq = answer.querySelector('blockquote')!
    expect(bq.textContent).toContain(CLAUSE)
    expect(within(bq as HTMLElement).getByText('Weather for Ferrymen contract')).toBeDefined()
    const legend = screen.getByRole('complementary', { name: 'Not in this answer' })
    expect(within(legend).getByText(/^3 items closed/)).toBeDefined()
    expect(within(legend).getByText('1 item at staff level, not read by the AI')).toBeDefined()
    expect(screen.getByRole('button', { name: /Board minutes September/ })).toBeDefined()
  })

  it('shows no withheld line and no staff-only list when the response has none', async () => {
    stubAsk(response({ withheld_from_ai: 0, staff_only_sources: [] }))
    render(<AskPage />)
    await ask()
    await screen.findByRole('region', { name: 'Answer' })
    expect(screen.queryByText(/closed to the AI/)).toBeNull()
    expect(screen.queryByText(/Also in the archive/)).toBeNull()
  })

  it('sets one plain line per kind of absence, with its count, beside the answer', async () => {
    const line = 'unused'
    stubAsk(response({
      silences: { closed: 3, closed_by: { writer: 1, default: 2, staff: 0 }, missing_correspondents: ['Ana R.'], empty_years: [2013, 2014, 2015], line },
    }))
    render(<AskPage />)
    await ask()
    const legend = await screen.findByTestId('silences')
    expect(within(legend).getAllByRole('listitem').slice(0, 4).map((l) => l.textContent)).toEqual([
      '1 item closed by its writer',
      '2 items closed by default (no one has opened them to the AI)',
      "Ana R.'s replies are not in the archive",
      'Nothing from 2013\u20132015',
    ])
    // Never an error or warning colour.
    expect(legend.innerHTML).not.toMatch(/var\(--(error|warning)/)
  })

  it('says so when there is nothing to report', async () => {
    stubAsk(response({
      withheld_from_ai: 0,
      staff_only_sources: [],
      silences: { closed: 0, missing_correspondents: [], empty_years: [], line: '' },
    }))
    render(<AskPage />)
    await ask()
    await screen.findByRole('region', { name: 'Answer' })
    expect(within(screen.getByTestId('silences')).getByText(/No closed items/)).toBeDefined()
  })

  it('not_answered: says so and what would answer it', async () => {
    stubAsk(response({ answer: [], not_answered: true, would_answer: 'The signed 2014 amendment.' }))
    render(<AskPage />)
    await ask()
    expect(await screen.findByText('The archive does not answer this.')).toBeDefined()
    expect(screen.getByText('What would: The signed 2014 amendment.')).toBeDefined()
  })

  it('not_answered without would_answer omits the second line', async () => {
    stubAsk(response({ answer: [], not_answered: true, would_answer: null }))
    render(<AskPage />)
    await ask()
    await screen.findByText('The archive does not answer this.')
    expect(screen.queryByText(/What would/)).toBeNull()
  })

  it('clicking a chip opens the passage with the quoted sentence highlighted', async () => {
    stubAsk(response())
    render(<AskPage />)
    const user = await ask()
    await screen.findByRole('region', { name: 'Answer' })
    expect(screen.queryByRole('complementary', { name: 'Source' })).toBeNull()
    await user.click(screen.getAllByLabelText('Source 1')[0])
    const panel = screen.getByRole('complementary', { name: 'Source' })
    expect(within(panel).getByText('Weather for Ferrymen contract')).toBeDefined()
    expect(within(panel).getByText('contract')).toBeDefined()
    // Named by its item, never by its file name.
    expect(within(panel).queryByText('notes/contracts/ferrymen.pdf')).toBeNull()
    expect(within(panel).getByTestId('source-sentence-1').getAttribute('data-cited')).toBeNull()
    // quote.sentence is 1-based: sentence 2 is the clause.
    const cited = within(panel).getByTestId('source-sentence-2')
    expect(cited.getAttribute('data-cited')).toBe('true')
    expect(cited.textContent).toContain(CLAUSE)
    expect(within(panel).getByTestId('source-sentence-3').getAttribute('data-cited')).toBeNull()
  })

  it('Open file sets the current file in the store, as the file tree does', async () => {
    stubAsk(response())
    render(<AskPage />)
    const user = await ask()
    await screen.findByRole('region', { name: 'Answer' })
    await user.click(screen.getAllByLabelText('Source 2')[0])
    await user.click(within(screen.getByRole('complementary', { name: 'Source' })).getByRole('button', { name: 'Open whole file' }))
    expect(useAppStore.getState().currentFile).toBe('notes/letters/estate.txt')
    expect(useAppStore.getState().leftTab).toBe('files')
  })

  it('a staff-only source opens its file', async () => {
    stubAsk(response())
    render(<AskPage />)
    const user = await ask()
    await user.click(await screen.findByRole('button', { name: /Board minutes September/ }))
    expect(useAppStore.getState().currentFile).toBe('notes/board/minutes.md')
  })

  it('keeps past questions, newest first, and re-shows an earlier answer', async () => {
    const first = response({ question: 'First question?', answer: [{ text: 'First answer.', cites: [1], quote: null }] })
    const second = response({ question: 'Second question?', answer: [{ text: 'Second answer.', cites: [1], quote: null }] })
    useAskStore.setState({ history: [second, first], activeIndex: 0 })
    render(<AskPage />)
    const list = screen.getByRole('list', { name: 'Past questions' })
    expect(within(list).getAllByRole('button').map((b) => b.textContent)).toEqual(['Second question?', 'First question?'])
    expect(screen.getByText('Second answer.')).toBeDefined()
    await userEvent.setup().click(within(list).getByRole('button', { name: 'First question?' }))
    expect(screen.getByText('First answer.')).toBeDefined()
    expect(screen.queryByText('Second answer.')).toBeNull()
  })

  it('shows Answering… with elapsed whole seconds while waiting, then clears it', async () => {
    let release!: (r: Response) => void
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>((res) => { release = res })))
    render(<AskPage />)
    await ask()
    expect(screen.getByRole('status').textContent).toBe('Answering… 0 s')
    release(new Response(JSON.stringify(response()), { status: 200 }))
    await screen.findByRole('region', { name: 'Answer' })
    expect(screen.queryByRole('status')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Stop' })).toBeNull()
  })

  it('counts elapsed seconds (fake timers)', () => {
    vi.useFakeTimers()
    try {
      vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(() => {})))
      render(<AskPage />)
      fireEvent.change(screen.getByLabelText('Question'), { target: { value: 'How long?' } })
      fireEvent.submit(screen.getByLabelText('Question').closest('form')!)
      expect(screen.getByRole('status').textContent).toBe('Answering… 0 s')
      act(() => { vi.advanceTimersByTime(12_400) })
      expect(screen.getByRole('status').textContent).toBe('Answering… 12 s')
    } finally {
      vi.useRealTimers()
    }
  })

  it('Stop aborts the request signal and leaves no error', async () => {
    let signal: AbortSignal | undefined
    vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => {
      if (String(url).includes('open-to-ai')) return Promise.resolve(new Response(JSON.stringify(OPEN)))
      signal = init?.signal ?? undefined
      return new Promise<Response>((_res, rej) => {
        signal?.addEventListener('abort', () => rej(new DOMException('Aborted', 'AbortError')))
      })
    }))
    render(<AskPage />)
    const user = await ask()
    expect(signal?.aborted).toBe(false)
    await user.click(screen.getByRole('button', { name: 'Stop' }))
    expect(signal?.aborted).toBe(true)
    await waitFor(() => expect(screen.queryByRole('status')).toBeNull())
    expect(screen.queryByRole('alert')).toBeNull()
    expect(useAskStore.getState().pending).toBeNull()
  })

  it('shows the question once: in the history list, not again as an answer heading', async () => {
    stubAsk(response({ question: 'Who gets subsidiary rights income?' }))
    render(<AskPage />)
    await ask()
    const answer = await screen.findByRole('region', { name: 'Answer' })
    expect(within(answer).queryByText('Who gets subsidiary rights income?')).toBeNull()
    expect(screen.getAllByText('Who gets subsidiary rights income?')).toHaveLength(1)
  })

  it('a sentence that is the quote word for word shows once, with where it is quoted from', async () => {
    stubAsk(response({ answer: [{ text: CLAUSE, cites: [1], quote: { passage: 1, sentence: 2, text: CLAUSE } }] }))
    render(<AskPage />)
    await ask()
    const answer = await screen.findByRole('region', { name: 'Answer' })
    expect(within(answer).getAllByText(CLAUSE, { exact: false })).toHaveLength(1)
    expect(within(answer).getByText('Quoted from Weather for Ferrymen contract')).toBeDefined()
  })

  it('on a phone the source covers the answer column instead of squeezing it', async () => {
    const w = window.innerWidth
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 390 })
    try {
      stubAsk(response())
      render(<AskPage />)
      await ask()
      const user = userEvent.setup()
      await user.click((await screen.findAllByLabelText('Source 1'))[0])
      const aside = screen.getByRole('complementary', { name: 'Source' })
      expect(aside.style.position).toBe('absolute')
      expect(aside.style.width).toBe('100%')
    } finally {
      Object.defineProperty(window, 'innerWidth', { configurable: true, value: w })
    }
  })

  it('503 says the local model is not running', async () => {
    stubAsk({ detail: 'down' }, 503)
    render(<AskPage />)
    await ask()
    await waitFor(() => expect(screen.getByRole('alert').textContent).toBe('The local model is not running.'))
  })

  it('says "1 item closed by its writer" in the singular, only when a writer closed it', async () => {
    stubAsk(response({ withheld_from_ai: 1, silences: { closed: 1, closed_by: { writer: 1, default: 0, staff: 0 }, missing_correspondents: [], empty_years: [], line: '' } }))
    render(<AskPage />)
    await ask()
    expect(await screen.findByText('1 item closed by its writer')).toBeDefined()
  })

  it('an item closed by the intake default is never said to be closed by its writer', async () => {
    stubAsk(response({ withheld_from_ai: 4, silences: { closed: 4, closed_by: { writer: 0, default: 4, staff: 0 }, missing_correspondents: [], empty_years: [], line: '' } }))
    render(<AskPage />)
    await ask()
    const legend = await screen.findByTestId('silences')
    expect(within(legend).getByText('4 items closed by default (no one has opened them to the AI)')).toBeDefined()
    expect(legend.textContent).not.toMatch(/writer/)
  })

  it('a withdrawn title and a title with no document each say so', async () => {
    stubAsk(response({
      answer: [], not_answered: true, passages: [], staff_only_sources: [], withheld_from_ai: 1,
      silences: {
        closed: 1, closed_by: { writer: 1, default: 0, staff: 0 }, missing_correspondents: [], empty_years: [], line: '',
        closed_named: [{ path: 'library/contracts/lanterns.pdf', title: 'Lanterns', kind: null, state: 'withdrawn', reason: 'withdrawn by its writer' }],
      },
    }))
    render(<AskPage />)
    await ask()
    expect(await screen.findByText(/The question is about Lanterns\. It is withdrawn by its writer/)).toBeDefined()
    cleanup()
    stubAsk(response({
      answer: [], not_answered: true, passages: [], staff_only_sources: [], withheld_from_ai: 0,
      would_answer: 'a contract for Ninety Tides',
      silences: { closed: 0, missing_correspondents: [], empty_years: [], line: '', no_document: { title: 'Ninety Tides', kind: 'contract' } },
    }))
    render(<AskPage />)
    await ask()
    const answer = await screen.findByRole('region', { name: 'Answer' })
    expect(within(answer).getByText('There is no contract for Ninety Tides in the archive.')).toBeDefined()
    expect(within(screen.getByTestId('silences')).getByText('There is no contract for Ninety Tides in the archive')).toBeDefined()
  })

  it('the question field has a placeholder and the form shares the 720 px measure', async () => {
    stubAsk(response())
    render(<AskPage />)
    const input = screen.getByLabelText('Question') as HTMLInputElement
    expect(input.placeholder).toBe('Ask about a contract, a title or the minutes')
    expect(input.closest('form')!.style.maxWidth).toBe('720px')
    await ask()
    const answer = await screen.findByRole('region', { name: 'Answer' })
    expect(answer.style.maxWidth).toBe('720px')
  })

  it('source panel: path wraps anywhere and the cited sentence is scrolled into view', async () => {
    const scroll = vi.fn()
    Element.prototype.scrollIntoView = scroll
    try {
      stubAsk(response())
      render(<AskPage />)
      const user = await ask()
      await screen.findByRole('region', { name: 'Answer' })
      await user.click(screen.getAllByLabelText('Source 1')[0])
      const panel = screen.getByRole('complementary', { name: 'Source' })
      expect(scroll).toHaveBeenCalledWith({ block: 'nearest' })
      expect(scroll.mock.instances[scroll.mock.instances.length - 1]).toBe(within(panel).getByTestId('source-sentence-2'))
    } finally {
      delete (Element.prototype as { scrollIntoView?: unknown }).scrollIntoView
    }
  })

  it('Open file on a cited PDF passes the highlighted sentence along with the page', async () => {
    const r = response()
    r.passages[0].page = 4
    stubAsk(r)
    render(<AskPage />)
    const user = await ask()
    await screen.findByRole('region', { name: 'Answer' })
    await user.click(screen.getAllByLabelText('Source 1')[0])
    await user.click(within(screen.getByRole('complementary', { name: 'Source' })).getByRole('button', { name: 'Open whole file' }))
    expect(useAppStore.getState().pdfTarget).toEqual({ path: 'notes/contracts/ferrymen.pdf', page: 4, text: CLAUSE })
  })

  it('the empty screen names what is open to the AI, by kind, from the backend counts', async () => {
    stubAsk(response())
    render(<AskPage />)
    const region = await screen.findByRole('region', { name: 'Open to the AI' })
    expect(within(region).getByText('Open to the AI: 12 items')).toBeDefined()
    expect(within(region).getAllByRole('listitem').map((l) => l.textContent)).toEqual(['contract6', 'letter1'])
    await ask()
    await screen.findByRole('region', { name: 'Answer' })
    expect(screen.queryByRole('region', { name: 'Open to the AI' })).toBeNull()
  })

  it('a passage is headed by its item and work with the ISBN, not a file name', async () => {
    const r = response()
    r.passages[0].work_title = 'Weather for Ferrymen'
    r.passages[0].isbn = '979-8-9001-0411-9'
    stubAsk(r)
    render(<AskPage />)
    const user = await ask()
    await screen.findByRole('region', { name: 'Answer' })
    await user.click(screen.getAllByLabelText('Source 1')[0])
    const panel = screen.getByRole('complementary', { name: 'Source' })
    expect(within(panel).getByRole('heading').textContent).toBe('Weather for Ferrymen contract: Weather for Ferrymen')
    expect(within(panel).getByText(/ISBN 979-8-9001-0411-9/)).toBeDefined()
  })

  it('a question naming a closed item shows the named closure', async () => {
    stubAsk(response({
      answer: [], not_answered: true, passages: [], staff_only_sources: [], withheld_from_ai: 1,
      silences: {
        closed: 1, missing_correspondents: [], empty_years: [], line: '',
        closed_named: [{ path: 'library/contracts/lanterns.pdf', title: 'Lanterns contract', kind: 'contract', state: 'closed', reason: 'closed by its writer' }],
      },
    }))
    render(<AskPage />)
    await ask()
    expect(await screen.findByText(/The question is about Lanterns contract\. It is closed by its writer/)).toBeDefined()
    expect(within(screen.getByTestId('silences')).getByText('Lanterns contract: closed by its writer')).toBeDefined()
  })

  it('a cited PDF page shows the passage highlight from the backend boxes', async () => {
    const r = response()
    r.passages[0].path = 'library/contracts/ferrymen.pdf'
    r.passages[0].page = 2
    const f = vi.fn(async (url: string) => {
      if (String(url).includes('open-to-ai')) return new Response(JSON.stringify(OPEN))
      if (String(url).includes('passage-boxes')) {
        return new Response(JSON.stringify({ page: 2, match: 'exact', boxes: [{ x: 0.1, y: 0.2, w: 0.5, h: 0.03 }] }))
      }
      return new Response(JSON.stringify(r))
    })
    vi.stubGlobal('fetch', f)
    render(<AskPage />)
    const user = await ask()
    await screen.findByRole('region', { name: 'Answer' })
    await user.click(screen.getAllByLabelText('Source 1')[0])
    const box = await screen.findByTestId('passage-highlight')
    expect(box.style.left).toBe('10%')
    expect(box.style.width).toBe('50%')
    expect(screen.getByAltText('Page 2')).toBeDefined()
    const asked = String((f.mock.calls as unknown[][]).map((c) => c[0]).find((u) => String(u).includes('passage-boxes')))
    expect(new URL('http://x' + asked).searchParams.get('text')).toBe(CLAUSE)
    expect(screen.queryByText(/nearest match/)).toBeNull()
  })

  it('when only the nearest lines match, the source panel says so', async () => {
    const r = response()
    r.passages[0].path = 'library/contracts/ferrymen.pdf'
    r.passages[0].page = 2
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (String(url).includes('open-to-ai')) return new Response(JSON.stringify(OPEN))
      if (String(url).includes('passage-boxes')) {
        return new Response(JSON.stringify({ page: 2, match: 'nearest', boxes: [{ x: 0.1, y: 0.2, w: 0.5, h: 0.03 }] }))
      }
      return new Response(JSON.stringify(r))
    }))
    render(<AskPage />)
    const user = await ask()
    await screen.findByRole('region', { name: 'Answer' })
    await user.click(screen.getAllByLabelText('Source 1')[0])
    expect(await screen.findByText(/nearest match/)).toBeDefined()
  })

  it('every control is at least 24 x 24 px', async () => {
    stubAsk(response())
    render(<AskPage />)
    await ask()
    await screen.findByRole('region', { name: 'Answer' })
    for (const el of [...screen.getAllByLabelText(/^Source \d$/), screen.getByRole('button', { name: 'Ask' }),
      ...within(screen.getByRole('list', { name: 'Past questions' })).getAllByRole('button')]) {
      expect(parseInt((el as HTMLElement).style.minHeight, 10)).toBeGreaterThanOrEqual(24)
      expect(parseInt((el as HTMLElement).style.minWidth, 10)).toBeGreaterThanOrEqual(24)
    }
  })
})
