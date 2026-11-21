import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { ExploreResponse } from '../../../lib/api/archive'
import { useArchiveViews } from '../viewStore'

const explore = vi.fn()
vi.mock('../../../lib/api/archive', () => ({ exploreArchive: (...a: unknown[]) => explore(...a) }))

import { ExploreView } from './ExploreView'

const passage = (n: number, name: string, date: string, titles: string[]) => ({
  n, path: `library/${name}`, name, kind: 'design', titles, date, year: Number(date.slice(0, 4)),
  chunk_id: n, ordinal: 0, page: null, char_start: 0, char_end: 5, text: `text ${n}`, how: 'phrase' as const, matched: ['yellow'],
})

const base = (over: Partial<ExploreResponse> = {}): ExploreResponse => ({
  query: 'yellow',
  passages: [passage(1, 'brief.md', '2019-03-12', []), passage(2, 'proof.txt', '2021-06-08', ['Ninety Tides'])],
  rows: [
    { title: 'Ninety Tides', isbn: '1', label: 'Ninety Tides', passages: [2] },
    { title: null, isbn: null, label: 'Press', passages: [1] },
  ],
  summary: [{ text: 'The band was chosen.', cites: [1], date: '2019-03-12' }],
  summary_status: 'ok', summary_shown: 1,
  not_open: { count: 1, reasons: [{ reason: 'private', kind: 'letter', count: 1, line: '1 letter closed by its writer' }] },
  model: 'm', prompt_version: 'v', timing: {},
  ...over,
} as ExploreResponse)

async function run(resp: ExploreResponse) {
  explore.mockResolvedValue(resp)
  render(<ExploreView />)
  fireEvent.change(screen.getByLabelText('Topic'), { target: { value: 'yellow' } })
  fireEvent.click(screen.getByRole('button', { name: 'Explore' }))
  await waitFor(() => expect(screen.getByTestId('not-open')).toBeTruthy())
}

describe('ExploreView', () => {
  beforeEach(() => {
    explore.mockReset()
    useArchiveViews.setState({ query: '', explore: null, exploreSelected: null })
  })

  it('draws one dot per returned passage and the closed items only as a count with reasons', async () => {
    await run(base())
    await waitFor(() => expect(document.querySelectorAll('button[data-dot]').length).toBe(2))
    const n = screen.getByTestId('not-open')
    expect(n.textContent).toContain('Not open to the AI: 1')
    expect(n.textContent).toContain('1 letter closed by its writer')
    expect(document.body.textContent).not.toContain('merrowby_spine-colour')
  })

  it('says in one line that the model did not answer, and keeps the dots', async () => {
    await run(base({ summary: [], summary_status: 'model_unavailable' }))
    await waitFor(() => expect(screen.getByText(/did not answer/)).toBeTruthy())
    expect(document.querySelectorAll('button[data-dot]').length).toBe(2)
  })

  it('clicking a cite opens its passage', async () => {
    await run(base())
    fireEvent.click(await screen.findByRole('button', { name: 'Document 1' }))
    expect(screen.getByRole('complementary', { name: 'Passage' }).textContent).toContain('brief.md')
  })
})
