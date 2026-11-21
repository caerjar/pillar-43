import { useState, useEffect, useMemo, useRef } from 'react'
import { api, type SearchResult } from '../../lib/api'
import { useAppStore } from '../../stores/appStore'
import { Spinner } from '../ui/Spinner'
import { FileResults } from './sections/FileResults'

type FlatItem = { kind: 'file'; result: SearchResult }


const RECENTS_KEY = 'search-recents'
const MAX_RECENTS = 5

function readRecents(): string[] {
  try {
    const stored = localStorage.getItem(RECENTS_KEY)
    if (stored) {
      const parsed = JSON.parse(stored)
      if (Array.isArray(parsed)) return parsed.filter((s): s is string => typeof s === 'string')
    }
  } catch {
    // localStorage not available or JSON parse error
  }
  return []
}

function addRecent(query: string): void {
  try {
    const current = readRecents()
    const deduped = [query, ...current.filter((q) => q !== query)].slice(0, MAX_RECENTS)
    localStorage.setItem(RECENTS_KEY, JSON.stringify(deduped))
  } catch {
    // localStorage not available
  }
}

interface Props {
  onClose: () => void
}

/**
 * ⌘K — fast file finder, with semantic matches underneath.
 *
 * Literal ripgrep matches come first and are never reordered: typing a
 * filename must put that file at the top. Below them, passages the vault's
 * embeddings judged close to the query, each carrying the text that matched
 * and badged `SEM` (see `sections/FileResults.tsx`).
 *
 * Semantic used to be hardcoded off here while the backend supported it, so
 * the app's headline capability was absent from its own search box. Two things
 * about the old backend behaviour explain why: it rendered a *score* rather
 * than a snippet, and it prepended its hits, demoting exact matches. Both are
 * fixed in `routes/search.py`; this passes the flag.
 *
 * Cost is ~7ms once warm (6ms to embed the query, ~1ms over 22k chunks), so it
 * rides the same request and the same 200ms debounce. The first query after a
 * restart pays a one-off ~0.5s to load the model and the vector matrix.
 *
 * For an answer rather than a list of files, use Ask, which retrieves and
 * cites.
 */
export function SearchPalette({ onClose }: Props) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<SearchResult[]>([])
  const [loading, setLoading] = useState(false)
  const [selected, setSelected] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [recents, setRecents] = useState<string[]>(() => readRecents())
  const inputRef = useRef<HTMLInputElement>(null)

  const setCurrentFile = useAppStore((s) => s.setCurrentFile)
  const setPendingLine = useAppStore((s) => s.setPendingLine)

  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  useEffect(() => {
    if (!query.trim()) {
      setResults([])
      return
    }
    const timer = setTimeout(async () => {
      setLoading(true)
      setError(null)
      try {
        const data = await api.search(query, 'all', undefined, true)
        setResults(data.results)
        setSelected(0)
        if (data.results.length > 0) {
          addRecent(query.trim())
          setRecents(readRecents())
        }
      } catch {
        setError('Search unavailable — check that the API is running')
        setResults([])
      } finally {
        setLoading(false)
      }
    }, 200)
    return () => clearTimeout(timer)
  }, [query])

  // Flat ordering for keyboard nav.
  const flat: FlatItem[] = useMemo(
    () => results.map((r) => ({ kind: 'file' as const, result: r })),
    [results],
  )

  // Reset selection when totals change so a stale index doesn't point past
  // the end of the new flat list.
  useEffect(() => {
    setSelected(0)
  }, [flat.length])

  const open = (result: SearchResult) => {
    setCurrentFile(result.path)
    onClose()
  }

  const openItem = (item: FlatItem) => {
    if (item.result.line && item.result.line > 0) setPendingLine(item.result.line)
    open(item.result)
  }

  const handleKey = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') { onClose(); return }
    if (e.key === 'ArrowDown') { e.preventDefault(); setSelected((s) => Math.min(s + 1, flat.length - 1)) }
    if (e.key === 'ArrowUp') { e.preventDefault(); setSelected((s) => Math.max(s - 1, 0)) }
    if (e.key === 'Enter') {
      if (flat[selected]) openItem(flat[selected])
    }
  }

  const showRecents = !query.trim() && recents.length > 0

  return (
    // Fix 4: outer wrapper also handles Escape so the palette closes even when
    // focus is on a result button rather than the text input.
    // Wrapper carries an onKeyDown for Escape so the palette closes even
    // when focus is on a result button rather than the input. It is
    // keyboard-operable already; it is simply not a control itself.
    // eslint-disable-next-line jsx-a11y/no-static-element-interactions
    <div
      data-testid="search-palette"
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 200,
        display: 'flex',
        alignItems: 'flex-start',
        justifyContent: 'center',
        paddingTop: '15vh',
        background: 'rgba(0,0,0,0.5)',
      }}
      onClick={(e) => e.target === e.currentTarget && onClose()}
      onKeyDown={(e) => { if (e.key === 'Escape') onClose() }}
    >
      <div
        style={{
          width: 600,
          background: 'var(--bg-panel)',
          border: '1px solid var(--border)',
          borderRadius: 8,
          overflow: 'hidden',
          boxShadow: 'var(--shadow-overlay)',
        }}
      >
        {/* Input row */}
        <div style={{ display: 'flex', alignItems: 'center', padding: '10px 14px', gap: 10 }}>
          <span style={{ color: 'var(--text-muted)', fontSize: 16 }}>⌕</span>
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKey}
            placeholder="Find a file…"
            data-testid="search-input"
            style={{
              flex: 1,
              background: 'transparent',
              border: 'none',
              outline: 'none',
              color: 'var(--text-primary)',
              fontSize: 15,
              fontFamily: 'var(--font-ui)',
            }}
          />
          {loading && <Spinner size="sm" label="Searching…" />}
          <kbd
            style={{
              background: 'var(--bg-active)',
              color: 'var(--text-muted)',
              border: '1px solid var(--border)',
              borderRadius: 3,
              padding: '1px 5px',
              fontSize: 10,
            }}
          >
            esc
          </kbd>
        </div>

        {error && (
          <div style={{ padding: '8px 14px', borderTop: '1px solid var(--border)', color: 'var(--accent)', fontSize: 12 }}>
            {error}
          </div>
        )}

        {showRecents && (
          <div
            data-testid="search-recents"
            style={{ padding: '8px 14px', borderBottom: '1px solid var(--border)' }}
          >
            <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 6 }}>
              Recent
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {recents.map((r) => (
                <button
                  key={r}
                  data-testid={`recent-chip-${r}`}
                  onClick={() => {
                    setQuery(r)
                    inputRef.current?.focus()
                  }}
                  style={{
                    padding: '2px 10px',
                    borderRadius: 10,
                    border: '1px solid var(--border)',
                    background: 'var(--bg-active)',
                    color: 'var(--text-secondary)',
                    fontSize: 12,
                    cursor: 'pointer',
                    fontFamily: 'var(--font-ui)',
                  }}
                >
                  {r}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Result count */}
        {!loading && results.length > 0 && (
          <div style={{ padding: '4px 14px', fontSize: 11, color: 'var(--text-muted)' }}>
            {results.length} file{results.length !== 1 ? 's' : ''}
          </div>
        )}

        {flat.length > 0 && (
          <div style={{ maxHeight: 400, overflow: 'auto' }}>
            <FileResults
              results={results}
              selected={selected}
              onOpen={open}
              onSelect={setSelected}
            />
          </div>
        )}

        {query && !loading && results.length === 0 && !error && (
          <div style={{ padding: '16px 14px', color: 'var(--text-muted)', fontSize: 13 }}>
            No matches. Ask a question in Ask.
          </div>
        )}
      </div>
    </div>
  )
}
