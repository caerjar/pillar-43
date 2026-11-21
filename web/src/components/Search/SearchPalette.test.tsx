import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { SearchPalette } from './SearchPalette'
import { api } from '../../lib/api'

vi.mock('../../lib/api', () => ({
  api: {
    search: vi.fn().mockResolvedValue({ results: [] }),
    experimentalGhostsSearch: vi.fn().mockResolvedValue({ ghosts: [] }),
    experimentalGapsSearch: vi.fn().mockResolvedValue({ gaps: [] }),
    cancelJob: vi.fn().mockResolvedValue({}),
  },
}))

const storeState = {
  setCurrentFile: vi.fn(),
  setPendingLine: vi.fn(),
  currentFile: null,
  setLastError: vi.fn(),
}

vi.mock('../../stores/appStore', () => ({
  useAppStore: Object.assign(
    (sel: (s: typeof storeState) => unknown) => sel(storeState),
    {
      getState: () => storeState,
      setState: (updater: (s: typeof storeState) => Partial<typeof storeState>) => {
        Object.assign(storeState, updater(storeState))
      },
    },
  ),
}))

vi.mock('../ui/Spinner', () => ({
  Spinner: () => <div data-testid="spinner" />,
}))

function renderWithClient(ui: React.ReactElement) {
  // Disable retries so a missing mock doesn't cause hung promises
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}


describe('SearchPalette — recent searches', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('shows no recents section when localStorage is empty', () => {
    renderWithClient(<SearchPalette onClose={() => {}} />)
    expect(screen.queryByTestId('search-recents')).toBeNull()
  })

  it('shows recents when localStorage has entries and query is empty', () => {
    localStorage.setItem('search-recents', JSON.stringify(['react hooks', 'fastapi']))
    renderWithClient(<SearchPalette onClose={() => {}} />)
    expect(screen.getByTestId('search-recents')).toBeTruthy()
    expect(screen.getByText('react hooks')).toBeTruthy()
    expect(screen.getByText('fastapi')).toBeTruthy()
  })

  it('clicking a recent chip fills the input', () => {
    localStorage.setItem('search-recents', JSON.stringify(['react hooks']))
    renderWithClient(<SearchPalette onClose={() => {}} />)
    fireEvent.click(screen.getByText('react hooks'))
    const input = screen.getByTestId('search-input') as HTMLInputElement
    expect(input.value).toBe('react hooks')
  })

  it('hides recents section when the query is non-empty', () => {
    localStorage.setItem('search-recents', JSON.stringify(['react hooks']))
    renderWithClient(<SearchPalette onClose={() => {}} />)
    const input = screen.getByTestId('search-input')
    fireEvent.change(input, { target: { value: 'vue' } })
    expect(screen.queryByTestId('search-recents')).toBeNull()
  })
})

describe('SearchPalette — semantic results', () => {
  it('asks the backend for semantic matches', async () => {
    // This was hardcoded `false` while the backend supported it, so Pillar-43's
    // headline capability was missing from its own search box. Watched failing
    // by passing `false` again.
    renderWithClient(<SearchPalette onClose={() => {}} />)
    fireEvent.change(screen.getByTestId('search-input'), { target: { value: 'grief' } })

    await waitFor(() => expect(vi.mocked(api.search)).toHaveBeenCalled())
    const calls = vi.mocked(api.search).mock.calls
    expect(calls[calls.length - 1][3], 'the semantic argument').toBe(true)
  })
})


describe('SearchPalette — scope and empty results', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('has no scope pills: one archive, searched whole', async () => {
    renderWithClient(<SearchPalette onClose={() => {}} />)
    for (const scope of ['all', 'notes', 'generated', 'thread']) {
      expect(screen.queryByRole('button', { name: scope })).toBeNull()
    }
    fireEvent.change(screen.getByTestId('search-input'), { target: { value: 'grief' } })
    await waitFor(() => expect(vi.mocked(api.search)).toHaveBeenCalled())
    const calls = vi.mocked(api.search).mock.calls
    expect(calls[calls.length - 1][1]).toBe('all')
  })

  it('points empty results at Ask, not at an AI chat', async () => {
    renderWithClient(<SearchPalette onClose={() => {}} />)
    fireEvent.change(screen.getByTestId('search-input'), { target: { value: 'zzzz' } })
    await waitFor(() => expect(screen.getByText(/No matches\. Ask a question in Ask\./)).toBeTruthy())
    expect(document.body.textContent).not.toMatch(/AI chat/)
  })
})
