/**
 * Ask, in the title-file form: the answer is set text with its quoted clauses
 * and sources; beside it, in the same type, what the archive could not say;
 * a citation opens the PDF page with the clause highlighted.
 *
 * Data flow is the old AskView's: askArchive with an AbortSignal, the
 * in-flight request at module level so Stop and the elapsed seconds survive
 * leaving the view and coming back.
 */
import { useEffect, useState, type FormEvent } from 'react'
import { useAskStore } from '../../../stores/askStore'
import { askArchive, ModelUnavailableError, type AskResponse, type AskPassage } from '../../../lib/api/archive'
import { errorMessage } from '../../../lib/errors'
import { OpenToAi } from './OpenToAi'
import { Silences } from './Silences'
import { SourcePanel } from './SourcePanel'
import { Button } from '../Button'
import { useOpenFile } from '../openFile'
import { muted, passageHeading, plainButton, target } from './styles'

const norm = (t: string) => t.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, ' ').trim()
const sameText = (a: string, b: string) => norm(a) === norm(b)

interface Selected { n: number; sentence: number | null }

let inflight: { controller: AbortController; startedAt: number } | null = null

function useElapsedSeconds(active: boolean): number {
  const [, tick] = useState(0)
  useEffect(() => {
    if (!active) return
    const id = setInterval(() => tick((n) => n + 1), 1000)
    return () => clearInterval(id)
  }, [active])
  return active && inflight ? Math.floor((Date.now() - inflight.startedAt) / 1000) : 0
}

export function AskPage() {
  const { history, activeIndex, pending, error, setPending, setError, addAnswer, show } = useAskStore()
  const [question, setQuestion] = useState('')
  const [selected, setSelected] = useState<Selected | null>(null)
  const openFile = useOpenFile()
  const elapsed = useElapsedSeconds(pending !== null)
  const active: AskResponse | null = activeIndex !== null ? history[activeIndex] ?? null : null

  async function submit(e: FormEvent) {
    e.preventDefault()
    const q = question.trim()
    if (!q || pending) return
    setPending(q)
    setError(null)
    setSelected(null)
    const controller = new AbortController()
    inflight = { controller, startedAt: Date.now() }
    try {
      addAnswer(await askArchive(q, controller.signal))
      setQuestion('')
    } catch (err) {
      setPending(null)
      // Stop is the person's choice, not a failure: no error, question kept.
      if (controller.signal.aborted) return
      setError(err instanceof ModelUnavailableError ? err.message : errorMessage(err))
    } finally {
      if (inflight?.controller === controller) inflight = null
    }
  }

  const selectedPassage: AskPassage | undefined = selected ? active?.passages.find((p) => p.n === selected.n) : undefined

  return (
    <div data-testid="ask-view" style={{ position: 'relative', flex: 1, display: 'flex', minHeight: 0, overflow: 'hidden' }}>
      <div style={{ flex: 1, minWidth: 0, overflowY: 'auto', padding: '24px 32px' }}>
        <form onSubmit={submit} style={{ display: 'flex', gap: 8, marginBottom: 20, maxWidth: 720 }}>
          <input
            aria-label="Question"
            placeholder="Ask about a contract, a title or the minutes"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            disabled={pending !== null}
            style={{
              flex: 1, minWidth: 0, minHeight: 32, padding: '4px 10px', fontSize: 'var(--text-sm)',
              fontFamily: 'inherit', background: 'var(--bg-base)', color: 'var(--text-primary)',
              border: '1px solid var(--border)', borderRadius: 4,
            }}
          />
          <Button type="submit" variant="primary" disabled={pending !== null || !question.trim()}>Ask</Button>
        </form>

        {pending !== null && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
            <div role="status" style={{ ...muted, color: 'var(--text-secondary)' }}>Answering… {elapsed} s</div>
            <Button onClick={() => inflight?.controller.abort()}>Stop</Button>
          </div>
        )}
        {error && (
          <div role="alert" style={{ color: 'var(--error)', fontSize: 'var(--text-sm)', marginBottom: 16 }}>{error}</div>
        )}

        {history.length > 0 && (
          <ul aria-label="Past questions" style={{ listStyle: 'none', margin: '0 0 24px', padding: 0, maxWidth: 720 }}>
            {history.map((h, i) => (
              <li key={`${i}-${h.question}`}>
                <button
                  type="button"
                  onClick={() => { show(i); setSelected(null) }}
                  aria-current={i === activeIndex ? 'true' : undefined}
                  style={{ ...plainButton, color: i === activeIndex ? 'var(--text-primary)' : 'var(--text-muted)' }}
                >
                  {h.question}
                </button>
              </li>
            ))}
          </ul>
        )}

        {history.length === 0 && pending === null && <OpenToAi />}

        {active && <AnswerSet r={active} selected={selected} onSelect={setSelected} onOpenFile={openFile} />}
      </div>

      {selectedPassage && (
        <SourcePanel
          passage={selectedPassage}
          highlight={selected?.sentence ?? null}
          onClose={() => setSelected(null)}
          onOpenFile={openFile}
        />
      )}
    </div>
  )
}

function AnswerSet({ r, selected, onSelect, onOpenFile }: {
  r: AskResponse
  selected: Selected | null
  onSelect: (s: Selected) => void
  onOpenFile: (path: string, page?: number | null, text?: string) => void
}) {
  const passageOf = (n: number) => r.passages.find((p) => p.n === n)
  const heading = (n: number) => { const p = passageOf(n); return p ? passageHeading(p) : '' }
  const named = r.silences?.closed_named ?? []
  const noDoc = r.silences?.no_document ?? null
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '24px 40px', alignItems: 'flex-start' }}>
      <section aria-label="Answer" style={{ flex: '1 1 420px', maxWidth: 720, minWidth: 0 }}>
        {r.not_answered ? (
          <div style={{ fontSize: 'var(--text-md)', color: 'var(--text-primary)' }}>
            {named.length > 0 ? (
              named.map((c) => (
                <p key={c.path} style={{ margin: '0 0 6px' }}>
                  The question is about {c.title}. It is {c.reason ?? 'closed'}, so the AI did not read it.
                </p>
              ))
            ) : noDoc ? (
              <p style={{ margin: '0 0 6px' }}>
                There is no {noDoc.kind} for {noDoc.title} in the archive.
              </p>
            ) : (
              <p style={{ margin: '0 0 6px' }}>The archive does not answer this.</p>
            )}
            {r.would_answer && named.length === 0 && !noDoc && (
              <p style={{ margin: 0, color: 'var(--text-secondary)' }}>What would: {r.would_answer}</p>
            )}
          </div>
        ) : (
          r.answer.map((s, i) => (
            <div key={i} style={{ marginBottom: 14 }}>
              <p style={{ margin: 0, fontSize: 'var(--text-md)', lineHeight: 1.6, color: 'var(--text-primary)' }}>
                {s.text}
                {s.cites.map((n) => {
                  const on = selected?.n === n
                  return (
                    <button
                      key={n}
                      type="button"
                      aria-label={`Source ${n}`}
                      aria-pressed={on}
                      onClick={() => onSelect({ n, sentence: s.quote && s.quote.passage === n ? s.quote.sentence : null })}
                      style={{
                        ...target, marginLeft: 4, padding: '0 6px', fontSize: 'var(--text-xs)', fontFamily: 'inherit',
                        cursor: 'pointer', borderRadius: 3, display: 'inline-flex', alignItems: 'center',
                        justifyContent: 'center', verticalAlign: 'middle',
                        background: on ? 'var(--accent-subtle)' : 'none',
                        color: 'var(--accent-text)', border: '1px solid var(--border-strong)',
                      }}
                    >
                      [{n}]
                    </button>
                  )
                })}
              </p>
              {s.quote && sameText(s.text, s.quote.text) ? (
                <div style={{ ...muted, marginTop: 2 }}>Quoted from {heading(s.quote.passage)}</div>
              ) : s.quote && (
                <blockquote style={{
                  margin: '8px 0 0 12px', padding: '4px 0 4px 12px', borderLeft: '2px solid var(--accent)',
                  color: 'var(--text-secondary)', fontSize: 'var(--text-sm)', lineHeight: 1.6,
                }}>
                  {s.quote.text}
                  <footer style={{ ...muted, marginTop: 2 }}>{heading(s.quote.passage)}</footer>
                </blockquote>
              )}
            </div>
          ))
        )}
      </section>
      <div style={{ flex: '0 1 280px', minWidth: 220 }}>
        <Silences r={r} onOpenFile={(p) => onOpenFile(p)} />
      </div>
    </div>
  )
}
