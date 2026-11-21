import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { TermsView } from './TermsView'

const OPTIONS = [
  { id: 'teaching_only', name: 'teaching only', meaning: 'The AI may use this work only for: teaching-packet.', aipref: 'ai-use=n, train-ai=n' },
  { id: 'never_for_training', name: 'never for training', meaning: 'The AI may not use this work for: training.', aipref: 'train-ai=n' },
]
const item = (over: Record<string, unknown> = {}) => ({
  path: 'library/contracts/lanterns-contract.pdf', title: 'Lanterns Contract', kind: 'contract',
  consent: 'model', labels: [], withdrawn_at: null,
  reads: [{ at: '2026-11-19T10:00:00+00:00', purpose: 'answering a staff question', receipt: 7 }],
  ...over,
})

function stub(items: unknown[]) {
  const calls: { url: string; body: unknown }[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === 'POST') calls.push({ url, body: JSON.parse(init.body as string) })
    return new Response(JSON.stringify({ items, label_options: OPTIONS }), { status: 200 })
  }))
  return calls
}
function renderView() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={qc}><TermsView /></QueryClientProvider>)
}
afterEach(() => vi.unstubAllGlobals())

describe('TermsView', () => {
  it('shows the title, the three levels with their meanings, and the access log without a question', async () => {
    stub([item()])
    renderView()
    expect(await screen.findByText('Lanterns Contract')).toBeTruthy()
    expect(screen.getByRole('radio', { name: /^Private/ })).toBeTruthy()
    expect(screen.getByRole('radio', { name: /^Staff/ })).toBeTruthy()
    expect((screen.getByRole('radio', { name: /^Model/ }) as HTMLInputElement).checked).toBe(true)
    expect(screen.getByText(/The AI may read it to answer staff questions/)).toBeTruthy()
    const log = screen.getByRole('list', { name: 'Access log for Lanterns Contract' })
    expect(log.textContent).toBe('2026-11-19, answering a staff question, answer receipt 7')
  })

  it('choosing Private posts the consent for that item', async () => {
    const calls = stub([item()])
    renderView()
    await userEvent.setup().click(await screen.findByRole('radio', { name: /^Private/ }))
    await waitFor(() => expect(calls).toEqual([{ url: '/api/archive/items/consent', body: { path: 'library/contracts/lanterns-contract.pdf', level: 'private' } }]))
  })

  it('adding a label posts the full set, and the notice shows its meaning in words', async () => {
    const calls = stub([item({ labels: [OPTIONS[0]] })])
    renderView()
    const row = within(await screen.findByTestId('terms-row-library/contracts/lanterns-contract.pdf'))
    expect(row.getByText('The AI may use this work only for: teaching-packet.')).toBeTruthy()
    expect(row.getByText('AI preference: ai-use=n, train-ai=n')).toBeTruthy()
    await userEvent.setup().click(row.getByRole('button', { name: 'Add label never for training to Lanterns Contract' }))
    await waitFor(() => expect(calls[0].body).toEqual({ path: 'library/contracts/lanterns-contract.pdf', labels: ['teaching_only', 'never_for_training'] }))
  })

  it('withdraw asks in place first; nothing is posted until the second click', async () => {
    const calls = stub([item()])
    renderView()
    const u = userEvent.setup()
    await u.click(await screen.findByRole('button', { name: 'Withdraw Lanterns Contract' }))
    expect(calls).toEqual([])
    expect(screen.getByText(/The archive forgets it and cannot take it back/)).toBeTruthy()
    await u.click(screen.getByRole('button', { name: 'Yes, withdraw' }))
    await waitFor(() => expect(calls).toEqual([{ url: '/api/archive/withdraw', body: { path: 'library/contracts/lanterns-contract.pdf' } }]))
  })

  it('Keep it closes the confirm without posting', async () => {
    const calls = stub([item()])
    renderView()
    const u = userEvent.setup()
    await u.click(await screen.findByRole('button', { name: 'Withdraw Lanterns Contract' }))
    await u.click(screen.getByRole('button', { name: 'Keep it' }))
    expect(screen.queryByRole('button', { name: 'Yes, withdraw' })).toBeNull()
    expect(calls).toEqual([])
  })

  it('a withdrawn row says so and offers no controls', async () => {
    stub([item({ consent: 'private', withdrawn_at: '2026-11-20T09:00:00+00:00' })])
    renderView()
    expect(await screen.findByText('Withdrawn on 2026-11-20')).toBeTruthy()
    expect(screen.queryByRole('button', { name: /Withdraw Lanterns/ })).toBeNull()
    expect(screen.getByRole('radio', { name: /^Model/ }).matches(':disabled')).toBe(true)
  })
})
