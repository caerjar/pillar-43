import type { SearchResult } from '../../../lib/api'

interface AskResult extends SearchResult {
  score?: number
}

export function FileResults({
  results,
  selected,
  onOpen,
  onSelect,
}: {
  results: AskResult[]
  selected: number
  onOpen: (r: AskResult) => void
  onSelect: (idx: number) => void
}) {
  return (
    <>
      {results.map((r, i) => {
        const flatIdx = i
        return (
          <button
            key={`${r.path}:${r.line}:${i}`}
            onClick={() => onOpen(r)}
            style={{
              display: 'block',
              width: '100%',
              textAlign: 'left',
              padding: '8px 14px',
              background: flatIdx === selected ? 'var(--bg-active)' : 'transparent',
              border: 'none',
              borderBottom: '1px solid var(--border)',
              cursor: 'pointer',
            }}
            onMouseEnter={() => onSelect(flatIdx)}
          >
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 2, display: 'flex', alignItems: 'center', gap: 4 }}>
              <span>{r.path}</span>
              {r.line > 0 && (
                <span style={{ color: 'var(--accent-dim)' }}>:{r.line}</span>
              )}
              {r.source === 'catalog' && (
                <span style={{
                  fontSize: 9, color: 'var(--accent)',
                  border: '1px solid var(--accent-dim)',
                  borderRadius: 3, padding: '0 4px',
                  fontFamily: 'var(--font-mono)',
                }}>
                  catalog
                </span>
              )}
              {r.source === 'semantic' && (
                <span style={{
                  fontSize: 9, color: 'var(--accent)',
                  border: '1px solid var(--accent-dim)',
                  borderRadius: 3, padding: '0 4px',
                  fontFamily: 'var(--font-mono)',
                }}>
                  ≈
                </span>
              )}
            </div>
            <div style={{ fontSize: 13, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>
              {r.text}
            </div>
            {r.note && (
              <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 3, fontStyle: 'italic' }}>
                {r.note}
              </div>
            )}
          </button>
        )
      })}
    </>
  )
}
