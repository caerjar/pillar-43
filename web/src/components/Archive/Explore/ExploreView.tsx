/**
 * Explore: a topic across the whole press. Rows are titles plus Press, each
 * matching document a dot at its date; below, the dated summary whose lines
 * cite the dots; beside it, how many matches are not open to the AI. The dots
 * come from the search and are shown first; the summary follows, with elapsed
 * seconds and Stop while it is written.
 */
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { exploreArchive } from '../../../lib/api/archive'
import { errorMessage } from '../../../lib/errors'
import { Button } from '../Button'
import { muted } from '../styles'
import { useArchiveViews } from '../viewStore'
import { formatDate, howMatched } from './layout'
import { NotOpen, PassagePanel } from './PassagePanel'
import { focusDot, Timeline, type TimelineItem } from './Timeline'

export function ExploreView() {
  const { query, explore, exploreSelected, set } = useArchiveViews()
  const [text, setText] = useState(query)
  const [searching, setSearching] = useState(false)
  const [summarizing, setSummarizing] = useState(false)
  const [stopped, setStopped] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [elapsed, setElapsed] = useState(0)
  const controller = useRef<AbortController | null>(null)
  const dotRefs = useRef(new Map<string, HTMLButtonElement>())

  useEffect(() => {
    if (!summarizing) return
    const start = Date.now()
    setElapsed(0)
    const id = setInterval(() => setElapsed(Math.floor((Date.now() - start) / 1000)), 1000)
    return () => clearInterval(id)
  }, [summarizing])

  async function submit(e: FormEvent) {
    e.preventDefault()
    const q = text.trim()
    if (!q || searching || summarizing) return
    const c = new AbortController()
    controller.current = c
    setError(null)
    setStopped(false)
    setSearching(true)
    set({ query: q, explore: null, exploreSelected: null })
    try {
      const found = await exploreArchive(q, { summarize: false, signal: c.signal })
      set({ explore: found })
      setSearching(false)
      if (found.passages.length > 0) {
        setSummarizing(true)
        try {
          const full = await exploreArchive(q, { summarize: true, signal: c.signal })
          set({ explore: full })
        } catch (err) {
          if (c.signal.aborted) setStopped(true)
          else setError(errorMessage(err))
        } finally {
          setSummarizing(false)
        }
      }
    } catch (err) {
      setSearching(false)
      if (!c.signal.aborted) setError(errorMessage(err))
    }
  }

  const items: TimelineItem[] = (explore?.passages ?? []).map((p) => ({
    n: p.n, name: p.name, date: p.date, year: p.year, how: howMatched(p.how, p.matched),
  }))
  const selected = explore?.passages.find((p) => p.n === exploreSelected)

  function cite(n: number) {
    set({ exploreSelected: n })
    focusDot(dotRefs.current, n)
  }

  return (
    <div data-testid="explore-view" style={{ position: 'relative', flex: 1, display: 'flex', minHeight: 0, overflow: 'hidden' }}>
      <div style={{ flex: 1, minWidth: 0, overflowY: 'auto', padding: '24px 32px' }}>
        <form onSubmit={submit} style={{ display: 'flex', gap: 8, marginBottom: 16, maxWidth: 720 }}>
          <input
            aria-label="Topic"
            placeholder="A topic, e.g. a colour, a clause, a name"
            value={text}
            onChange={(e) => setText(e.target.value)}
            style={{
              flex: 1, minWidth: 0, padding: '8px 10px', fontSize: 'var(--text-md)', fontFamily: 'inherit',
              background: 'var(--bg-base)', color: 'var(--text-primary)',
              border: '1px solid var(--border)', borderRadius: 4,
            }}
          />
          <Button type="submit" variant="primary" disabled={searching || summarizing || !text.trim()}>
            Explore
          </Button>
        </form>

        {searching && <div role="status" style={{ ...muted, marginBottom: 12 }}>Searching…</div>}
        {error && <div role="alert" style={{ color: 'var(--error)', fontSize: 'var(--text-sm)', marginBottom: 12 }}>{error}</div>}

        {explore && explore.passages.length === 0 && (
          <p style={{ fontSize: 'var(--text-md)', color: 'var(--text-primary)', margin: '0 0 16px' }}>
            No document open to the AI matches “{explore.query}”.
          </p>
        )}

        {explore && explore.passages.length > 0 && (
          <>
            <Timeline
              label={`Documents matching ${explore.query}, by title and year`}
              rows={explore.rows}
              items={items}
              selected={exploreSelected}
              onSelect={(n) => set({ exploreSelected: n })}
              registerDot={(k, el) => { if (el) dotRefs.current.set(k, el); else dotRefs.current.delete(k) }}
            />

            <section aria-label="Summary" style={{ marginTop: 24, maxWidth: 720 }}>
              {summarizing && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8 }}>
                  <div role="status" style={muted}>Writing the summary… {elapsed} s</div>
                  <Button type="button" variant="plain" onClick={() => controller.current?.abort()}>Stop</Button>
                </div>
              )}
              {stopped && <p style={{ ...muted, margin: '0 0 8px' }}>Stopped. The documents are complete; there is no summary.</p>}
              {explore.summary_status === 'model_unavailable' && (
                <p style={{ ...muted, margin: '0 0 8px' }}>The model did not answer, so there is no summary. The documents above are complete.</p>
              )}
              {explore.summary_status === 'none_valid' && (
                <p style={{ ...muted, margin: '0 0 8px' }}>No summary line could be tied to a document.</p>
              )}
              {explore.summary.length > 0 && (
                <ol style={{ listStyle: 'none', margin: 0, padding: 0 }}>
                  {explore.summary.map((l, i) => (
                    <li key={i} style={{ marginBottom: 10, fontSize: 'var(--text-md)', lineHeight: 1.6, color: 'var(--text-primary)' }}>
                      {l.date && <span style={{ color: 'var(--text-secondary)' }}>{formatDate(l.date)}: </span>}
                      {l.text}
                      {l.cites.map((n) => (
                        <button
                          key={n}
                          type="button"
                          aria-label={`Document ${n}`}
                          aria-pressed={exploreSelected === n}
                          onClick={() => cite(n)}
                          style={{
                            marginLeft: 4, minWidth: 24, minHeight: 24, fontSize: 'var(--text-xs)', fontFamily: 'inherit', cursor: 'pointer',
                            borderRadius: 3, background: exploreSelected === n ? 'var(--accent-subtle)' : 'none',
                            color: 'var(--accent-text)', border: '1px solid var(--border-strong)',
                          }}
                        >
                          [{n}]
                        </button>
                      ))}
                    </li>
                  ))}
                </ol>
              )}
            </section>
          </>
        )}

        {explore && (
          <div style={{ marginTop: 24, maxWidth: 720 }}>
            <NotOpen count={explore.not_open.count} lines={explore.not_open.reasons.map((r) => r.line)} />
          </div>
        )}
      </div>

      {selected && (
        <PassagePanel
          passage={{ ...selected, how: howMatched(selected.how, selected.matched) }}
          onClose={() => set({ exploreSelected: null })}
        />
      )}
    </div>
  )
}
