import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { PDFViewer } from './PDFViewer'

// A citation opens its PDF at the page the passage starts on (MVP step 4).
describe('PDFViewer initialPage', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ page_count: 3 }) })))
  })
  afterEach(() => vi.unstubAllGlobals())

  const url = '/api/file/raw?path=library%2Fcontracts%2Fc.pdf'

  it('opens at page 1 by default', async () => {
    render(<PDFViewer url={url} />)
    await waitFor(() => expect(screen.getByText('1 / 3')).toBeTruthy())
    expect(screen.getByAltText('Page 1').getAttribute('src')).toContain('page=1&')
  })

  it('opens at the cited page', async () => {
    render(<PDFViewer url={url} initialPage={2} />)
    await waitFor(() => expect(screen.getByText('2 / 3')).toBeTruthy())
    expect(screen.getByAltText('Page 2').getAttribute('src')).toContain('page=2&')
  })

  it('moves when another citation in the same file is opened', async () => {
    const { rerender } = render(<PDFViewer url={url} initialPage={2} />)
    await waitFor(() => expect(screen.getByText('2 / 3')).toBeTruthy())
    rerender(<PDFViewer url={url} initialPage={3} />)
    await waitFor(() => expect(screen.getByText('3 / 3')).toBeTruthy())
  })
})
