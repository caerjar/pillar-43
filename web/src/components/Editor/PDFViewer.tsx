import { useEffect, useState } from 'react'
// See apiBase.test.ts: a root-relative '/api/...' only resolves because nginx
// and the Vite dev server happen to proxy it at the app's own origin.
import { BASE } from '../../lib/api/_fetch'

interface Props {
  url: string
  onAnnotate?: () => void
  /** Page to open at: a cited passage's page. Changing it moves the view. */
  initialPage?: number
}

const btnBase: React.CSSProperties = {
  padding: '2px 8px',
  background: 'transparent',
  color: 'var(--text-secondary)',
  border: '1px solid var(--border)',
  borderRadius: 3,
  cursor: 'pointer',
  fontSize: 12,
}
const btnOff: React.CSSProperties = { ...btnBase, opacity: 0.35, cursor: 'default' }

// Not a token: the tray framing the rendered page is deliberately fixed dark
// in both themes, because the PDF itself is always a white sheet. A
// theme-reactive surface token inverts to near-white in light mode and the
// page loses its frame entirely.
const PDF_TRAY_BG = '#3a3530'

export function PDFViewer({ url, onAnnotate, initialPage }: Props) {
  const [numPages, setNumPages] = useState(0)
  const [pageNum, setPageNum] = useState(initialPage ?? 1)
  const [scale, setScale] = useState(1.5)
  const [loadedUrl, setLoadedUrl] = useState('')   // which pageUrl has finished loading
  const [error, setError] = useState<string | null>(null)

  // Extract path param from the raw-file URL (e.g. /api/file/raw?path=library/...)
  const pathParam = new URL(url, window.location.origin).searchParams.get('path') ?? ''
  const dpi = Math.round(72 * scale)
  const pageUrl = `${BASE}/api/file/pdf-page?path=${encodeURIComponent(pathParam)}&page=${pageNum}&dpi=${dpi}`

  // Derived — no effect needed, no race condition with cached images
  const imgLoading = loadedUrl !== pageUrl

  // Fetch page count once per PDF; reset all per-PDF state
  useEffect(() => {
    setPageNum(initialPage ?? 1)
    setError(null)
    setLoadedUrl('')
    setNumPages(0)
    if (!pathParam) return
    fetch(`${BASE}/api/file/pdf-info?path=${encodeURIComponent(pathParam)}`)
      .then((r) => r.ok ? r.json() : Promise.reject(r.status))
      .then((d) => setNumPages(d.page_count ?? 0))
      .catch(() => setError('Could not load PDF info'))
    // initialPage is read here only for a new PDF; the effect below moves
    // within the same PDF without refetching its info.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathParam])

  useEffect(() => {
    if (initialPage) setPageNum(initialPage)
  }, [initialPage])

  const toolbar = (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 12px', background: 'var(--bg-panel)', borderBottom: '1px solid var(--border)', flexShrink: 0 }}>
      <button style={pageNum <= 1 ? btnOff : btnBase} disabled={pageNum <= 1}
        onClick={() => setPageNum((p) => Math.max(1, p - 1))}>←</button>
      <span style={{ fontSize: 12, color: 'var(--text-muted)', minWidth: 60, textAlign: 'center' }}>
        {numPages === 0 ? 'Loading…' : `${pageNum} / ${numPages}`}
      </span>
      <button style={pageNum >= numPages ? btnOff : btnBase} disabled={pageNum >= numPages}
        onClick={() => setPageNum((p) => Math.min(numPages, p + 1))}>→</button>
      <div style={{ width: 1, height: 16, background: 'var(--border)', margin: '0 4px' }} />
      <button style={scale <= 0.5 ? btnOff : btnBase} disabled={scale <= 0.5}
        onClick={() => setScale((s) => Math.max(0.5, +(s - 0.25).toFixed(2)))}>−</button>
      <span style={{ fontSize: 11, color: 'var(--text-muted)', minWidth: 36, textAlign: 'center' }}>
        {Math.round(scale * 100)}%
      </span>
      <button style={scale >= 3 ? btnOff : btnBase} disabled={scale >= 3}
        onClick={() => setScale((s) => Math.min(3, +(s + 0.25).toFixed(2)))}>+</button>
      <div style={{ flex: 1 }} />
      {onAnnotate && (
        <button
          onClick={onAnnotate}
          title="Open annotation note"
          style={{ ...btnBase, fontSize: 11 }}
        >
          Annotate
        </button>
      )}
      <a href={url} target="_blank" rel="noopener noreferrer"
        style={{ fontSize: 11, color: 'var(--text-muted)', textDecoration: 'none' }}
        title="Open in system viewer">↗</a>
    </div>
  )

  if (error) {
    return (
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        {toolbar}
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', flexDirection: 'column', gap: 12, color: 'var(--text-muted)', fontSize: 13 }}>
          <span>{error}</span>
          <a href={url} target="_blank" rel="noopener noreferrer" style={{ color: 'var(--accent)', fontSize: 12 }}>
            Open in system viewer ↗
          </a>
        </div>
      </div>
    )
  }

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      {toolbar}
      <div style={{ flex: 1, overflow: 'auto', display: 'flex', justifyContent: 'center', padding: '24px 16px', background: PDF_TRAY_BG }}>
        {imgLoading && (
          <div style={{ position: 'absolute', color: 'var(--text-muted)', fontSize: 13, alignSelf: 'center' }}>
            Rendering…
          </div>
        )}
        {numPages > 0 && (
          <img
            key={pageUrl}
            src={pageUrl}
            alt={`Page ${pageNum}`}
            style={{
              display: imgLoading ? 'none' : 'block',
              maxWidth: '100%',
              boxShadow: '0 2px 16px rgba(0,0,0,0.5)',
              borderRadius: 2,
            }}
            onLoad={() => setLoadedUrl(pageUrl)}
            onError={() => { setLoadedUrl(pageUrl); setError(`Failed to render page ${pageNum}`) }}
          />
        )}
      </div>
    </div>
  )
}
