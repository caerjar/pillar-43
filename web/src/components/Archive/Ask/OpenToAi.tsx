/**
 * The empty Ask screen: what is open to the AI, by kind. The counts are the
 * backend's (GET /api/archive/open-to-ai); nothing is derived here.
 */
import { useEffect, useState } from 'react'
import { fetchOpenToAi, type OpenToAi as Counts } from '../../../lib/api/archive'
import { muted } from './styles'

export function OpenToAi() {
  const [counts, setCounts] = useState<Counts | null>(null)
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    const ctl = new AbortController()
    fetchOpenToAi(ctl.signal).then(setCounts).catch(() => { if (!ctl.signal.aborted) setFailed(true) })
    return () => ctl.abort()
  }, [])
  if (failed) return <p style={muted}>What is open to the AI could not be read.</p>
  if (!counts || !Array.isArray(counts.by_kind)) return null
  return (
    <section aria-label="Open to the AI" style={{ maxWidth: 420 }}>
      <h2 style={{ margin: '0 0 4px', fontSize: 'var(--text-sm)', fontWeight: 600, color: 'var(--text-primary)' }}>
        Open to the AI: {counts.total} {counts.total === 1 ? 'item' : 'items'}
      </h2>
      <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
        {counts.by_kind.map((k) => (
          <li
            key={k.kind}
            style={{
              display: 'flex', justifyContent: 'space-between', gap: 16, padding: '3px 0',
              borderBottom: '1px solid var(--border)', fontSize: 'var(--text-sm)', color: 'var(--text-secondary)',
            }}
          >
            <span>{k.kind}</span>
            <span>{k.count}</span>
          </li>
        ))}
      </ul>
    </section>
  )
}
