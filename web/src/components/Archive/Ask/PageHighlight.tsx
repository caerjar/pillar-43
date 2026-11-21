/**
 * A PDF page with the cited passage highlighted on it. The page is rendered
 * by the server (PDFium); the boxes come from the same engine's glyph
 * positions (GET /api/archive/passage-boxes), as fractions of the page.
 */
import { useEffect, useState } from 'react'
import { BASE } from '../../../lib/api/_fetch'
import { fetchPassageBoxes, type PassageBoxes } from '../../../lib/api/archive'
import { muted } from './styles'

// Deliberate literal: a PDF page is a white paper sheet in both themes, and
// the highlight boxes are drawn over it, so it must NOT follow the theme.
const PAGE_WHITE = '#ffffff'

/** A passage can run over a page break; look at the next pages too. */
const PAGES_AHEAD = 2

export function PageHighlight({ path, page, text }: { path: string; page: number; text: string }) {
  const [found, setFound] = useState<PassageBoxes | null>(null)
  const [done, setDone] = useState(false)

  useEffect(() => {
    const ctl = new AbortController()
    setFound(null)
    setDone(false)
    ;(async () => {
      let first: PassageBoxes | null = null
      for (let p = page; p <= page + PAGES_AHEAD; p++) {
        try {
          const r = await fetchPassageBoxes(path, p, text, ctl.signal)
          if (r.match === 'exact') { setFound(r); return }
          if (r.match === 'nearest' && !first) first = r
        } catch {
          if (ctl.signal.aborted) return
          break
        }
      }
      setFound(first)
    })().finally(() => { if (!ctl.signal.aborted) setDone(true) })
    return () => ctl.abort()
  }, [path, page, text])

  const shown = found?.page ?? page
  const src = `${BASE}/api/file/pdf-page?path=${encodeURIComponent(path)}&page=${shown}&dpi=100`
  return (
    <figure style={{ margin: '0 0 12px' }}>
      <div data-testid="pdf-page" style={{ position: 'relative', lineHeight: 0, border: '1px solid var(--border)', background: PAGE_WHITE }}>
        <img src={src} alt={`Page ${shown}`} style={{ width: '100%', height: 'auto', display: 'block' }} />
        {found?.boxes.map((b, i) => (
          <div
            key={i}
            data-testid="passage-highlight"
            data-match={found.match}
            style={{
              position: 'absolute', left: `${b.x * 100}%`, top: `${b.y * 100}%`,
              width: `${b.w * 100}%`, height: `${b.h * 100}%`,
              background: 'var(--accent)', opacity: 0.32, mixBlendMode: 'multiply',
              outline: '1px solid var(--accent)', pointerEvents: 'none',
            }}
          />
        ))}
      </div>
      <figcaption style={{ ...muted, marginTop: 4 }} role="status">
        Page {shown}
        {found?.match === 'nearest' && ' · nearest match: the passage is not on the page word for word'}
        {done && !found && ' · the passage could not be located on this page'}
      </figcaption>
    </figure>
  )
}
