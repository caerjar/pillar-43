/**
 * The passage behind a dot, with its page. A PDF dot shows the page with the
 * passage highlighted, the same PageHighlight (GET /api/archive/passage-boxes)
 * that Ask's source panel uses. "Open whole file" opens it in the viewer.
 */
import type { CSSProperties } from 'react'
import { Button } from '../Button'
import { PageHighlight } from '../Ask/PageHighlight'
import { muted } from '../styles'
import { useOpenFile } from '../openFile'
import { formatDate } from './layout'

export interface PanelPassage {
  n: number
  path: string
  name: string
  kind: string
  titles: string[]
  date?: string | null
  year?: number | null
  page?: number | null
  text: string
  how: string
  /** Words to mark in the text: the matched terms, or a person's name. */
  matched?: string[]
}

const escape = (t: string) => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

/** The text with each matched word or name in a <mark>. */
export function Marked({ text, terms }: { text: string; terms: string[] }) {
  const words = [...new Set(terms.map((t) => t.trim()).filter(Boolean))].sort((x, y) => y.length - x.length)
  if (words.length === 0) return <>{text}</>
  const parts = text.split(new RegExp(`(${words.map(escape).join('|')})`, 'gi'))
  return (
    <>
      {parts.map((part, i) => (i % 2 === 1 ? <mark key={i} style={MARK}>{part}</mark> : part))}
    </>
  )
}

// Text on the warning tint: 7.8:1 in the dark theme, far above 4.5:1 in the
// light one. An underline too, so the mark is not carried by colour alone.
const MARK: CSSProperties = {
  background: 'var(--warning-dim)', color: 'var(--text-primary)', borderRadius: 2,
  textDecoration: 'underline', textDecorationColor: 'var(--accent)', textUnderlineOffset: 2,
}

export function PassagePanel({ passage, onClose }: { passage: PanelPassage; onClose: () => void }) {
  const open = useOpenFile()
  const date = formatDate(passage.date, passage.year)
  const isPdf = passage.path.toLowerCase().endsWith('.pdf')
  return (
    <aside
      aria-label="Passage"
      style={{
        width: 340, flexShrink: 0, overflowY: 'auto', padding: '24px 20px', boxSizing: 'border-box',
        borderLeft: '1px solid var(--border)', background: 'var(--bg-panel)',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
        <h2 style={{ flex: 1, margin: 0, fontSize: 'var(--text-md)', fontWeight: 600, color: 'var(--text-primary)', overflowWrap: 'anywhere' }}>
          {passage.name}
        </h2>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close passage"
          style={{ minWidth: 24, minHeight: 24, background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-muted)', fontSize: 'var(--text-lg)', lineHeight: 1 }}
        >×</button>
      </div>
      <div style={{ ...muted, margin: '2px 0' }}>
        {passage.kind}{date ? `, ${date}` : ''}{passage.page ? `, page ${passage.page}` : ''}
      </div>
      {passage.titles.length > 0 && <div style={{ ...muted, margin: '0 0 4px' }}>{passage.titles.join(', ')}</div>}
      <div style={{ ...muted, margin: '0 0 8px' }}>{passage.how}</div>
      <p
        data-testid="passage-text"
        style={{
          margin: '8px 0 12px', padding: '4px 0 4px 10px', borderLeft: '2px solid var(--accent)',
          fontSize: 'var(--text-sm)', lineHeight: 1.55, color: 'var(--text-primary)', whiteSpace: 'pre-wrap',
        }}
      >
        {isPdf ? passage.text : <Marked text={passage.text} terms={passage.matched ?? []} />}
      </p>
      {isPdf && passage.page ? (
        <PageHighlight path={passage.path} page={passage.page} text={passage.text} />
      ) : null}
      <Button onClick={() => open(passage.path, passage.page, passage.text)}>Open whole file</Button>
    </aside>
  )
}

/** The closed-to-the-AI notice: a count and one plain line per reason. */
export function NotOpen({ count, lines }: { count: number; lines: string[] }) {
  return (
    <section aria-label="Not open to the AI" data-testid="not-open">
      <h3 style={{ margin: '0 0 6px', fontSize: 'var(--text-sm)', fontWeight: 600, color: 'var(--text-primary)' }}>
        Not open to the AI: {count}
      </h3>
      <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
        {lines.map((l) => (
          <li key={l} style={{ fontSize: 'var(--text-sm)', color: 'var(--text-secondary)', padding: '1px 0' }}>{l}</li>
        ))}
      </ul>
    </section>
  )
}
