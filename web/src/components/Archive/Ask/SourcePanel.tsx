/**
 * The source of one citation: the item and the work it is about, the PDF page
 * with the cited clause highlighted, and the passage as the model read it.
 */
import { useEffect, useRef } from 'react'
import { useViewport } from '../../../hooks/useViewport'
import type { AskPassage } from '../../../lib/api/archive'
import { Button } from '../Button'
import { PageHighlight } from './PageHighlight'
import { muted, passageHeading } from './styles'

interface Props {
  passage: AskPassage
  /** 1-based index of the quoted sentence, when the citation carries one. */
  highlight: number | null
  onClose: () => void
  onOpenFile: (path: string, page?: number | null, text?: string) => void
}

export function SourcePanel({ passage, highlight, onClose, onOpenFile }: Props) {
  // On a phone a 360 px column leaves the answer one word wide, so the
  // passage covers the answer instead, and Close goes back to it.
  const { tiny } = useViewport()
  const citedRef = useRef<HTMLLIElement | null>(null)
  useEffect(() => {
    citedRef.current?.scrollIntoView?.({ block: 'nearest' })
  }, [passage, highlight])
  const citedText = highlight !== null ? passage.sentences[highlight - 1] : undefined
  const isPdf = passage.path.toLowerCase().endsWith('.pdf')
  // The quoted sentence when there is one, else the whole passage.
  const onPage = citedText ?? passage.sentences.join(' ')
  return (
    <aside
      aria-label="Source"
      style={{
        ...(tiny ? { position: 'absolute', inset: 0, width: '100%', zIndex: 1 } : { width: 'min(520px, 42%)', minWidth: 360, flexShrink: 0 }),
        overflowY: 'auto', padding: '20px', boxSizing: 'border-box',
        borderLeft: '1px solid var(--border)', background: 'var(--bg-panel)',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8 }}>
        <h2 style={{ flex: 1, margin: 0, fontSize: 'var(--text-sm)', fontWeight: 600, color: 'var(--text-primary)' }}>
          {passageHeading(passage)}
        </h2>
        <Button onClick={onClose}>Close source</Button>
      </div>
      <div style={{ ...muted, margin: '2px 0 8px' }}>
        {passage.kind}
        {passage.isbn ? ` · ISBN ${passage.isbn}` : ''}
        {passage.heading ? ` · ${passage.heading}` : ''}
      </div>
      {isPdf && passage.page ? (
        <PageHighlight path={passage.path} page={passage.page} text={onPage} />
      ) : null}
      <div style={{ margin: '0 0 12px' }}>
        <Button onClick={() => onOpenFile(passage.path, passage.page, citedText)}>Open whole file</Button>
      </div>
      <ol style={{ margin: 0, padding: 0, listStyle: 'none' }}>
        {passage.sentences.map((t, i) => {
          const on = i + 1 === highlight
          return (
            <li
              key={i}
              data-testid={`source-sentence-${i + 1}`}
              data-cited={on ? 'true' : undefined}
              ref={on ? citedRef : undefined}
              style={{
                display: 'flex', gap: 8, padding: '3px 6px', fontSize: 'var(--text-sm)', lineHeight: 1.55,
                color: on ? 'var(--text-primary)' : 'var(--text-secondary)',
                background: on ? 'var(--accent-subtle)' : 'none',
                borderLeft: on ? '2px solid var(--accent)' : '2px solid transparent',
              }}
            >
              <span style={{ ...muted, flexShrink: 0, minWidth: 18 }}>{i + 1}</span>
              <span>{t}</span>
            </li>
          )
        })}
      </ol>
    </aside>
  )
}
