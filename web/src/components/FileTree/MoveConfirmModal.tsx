import { useEffect, useState } from 'react'
import { api } from '../../lib/api'
import { errorMessage } from '../../lib/errors'

interface LinkChange {
  file: string
  line: number
  old_text: string
  new_text: string
}

interface Props {
  src: string
  dest: string
  onConfirm: (applyLinks: boolean) => void
  onCancel: () => void
}

export function MoveConfirmModal({ src, dest, onConfirm, onCancel }: Props) {
  const [changes, setChanges] = useState<LinkChange[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.movePreview(src, dest)
      .then((r) => setChanges(r.changes))
      .catch((e) => setError(errorMessage(e)))
      .finally(() => setLoading(false))
  }, [src, dest])

  // Group changes by file
  const byFile: Record<string, LinkChange[]> = {}
  for (const c of changes ?? []) {
    ;(byFile[c.file] ??= []).push(c)
  }
  const fileList = Object.entries(byFile)

  return (
    // Modal backdrop. Escape cancels too, so the click is a mouse
    // convenience rather than the only way out; a tab stop here would
    // announce nothing.
    // eslint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/no-static-element-interactions
    <div
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0,0,0,0.55)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 200,
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onCancel() }}
    >
      <div
        style={{
          background: 'var(--bg-panel)',
          border: '1px solid var(--border)',
          borderRadius: 8,
          width: 520,
          maxHeight: '70vh',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
          boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
        }}
      >
        {/* Header */}
        <div style={{ padding: '14px 16px 10px', borderBottom: '1px solid var(--border)', flexShrink: 0 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 6 }}>
            Confirm move
          </div>
          <div style={{ fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--text-muted)' }}>
            <span style={{ color: 'var(--text-secondary)' }}>{src}</span>
            <span style={{ margin: '0 6px', color: 'var(--accent)' }}>→</span>
            <span style={{ color: 'var(--text-secondary)' }}>{dest}</span>
          </div>
        </div>

        {/* Link changes */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '10px 16px' }}>
          {loading && (
            <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>Scanning for links…</div>
          )}
          {error && (
            <div style={{ color: 'var(--error)', fontSize: 12 }}>{error}</div>
          )}
          {!loading && !error && fileList.length === 0 && (
            <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>
              No link changes needed — no files reference this path.
            </div>
          )}
          {!loading && fileList.length > 0 && (
            <>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 8 }}>
                {changes!.length} link{changes!.length !== 1 ? 's' : ''} in {fileList.length} file{fileList.length !== 1 ? 's' : ''} will be updated:
              </div>
              {fileList.map(([file, fileChanges]) => (
                <div key={file} style={{ marginBottom: 10 }}>
                  <div style={{ fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--accent)', marginBottom: 4 }}>
                    {file}
                  </div>
                  {fileChanges.map((c, i) => (
                    <div key={i} style={{ paddingLeft: 10, marginBottom: 3 }}>
                      <div style={{ fontSize: 10, color: 'var(--error)', fontFamily: 'var(--font-mono)' }}>
                        − {c.old_text}
                      </div>
                      <div style={{ fontSize: 10, color: 'var(--success)', fontFamily: 'var(--font-mono)' }}>
                        + {c.new_text}
                      </div>
                      <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>line {c.line}</div>
                    </div>
                  ))}
                </div>
              ))}
            </>
          )}
        </div>

        {/* Actions */}
        <div
          style={{
            padding: '10px 16px',
            borderTop: '1px solid var(--border)',
            display: 'flex',
            gap: 8,
            flexShrink: 0,
          }}
        >
          <button
            onClick={() => onConfirm(true)}
            disabled={loading}
            style={{
              padding: '5px 14px',
              background: 'var(--accent)',
              color: 'var(--on-accent)',
              border: 'none',
              borderRadius: 4,
              cursor: loading ? 'not-allowed' : 'pointer',
              fontSize: 12,
              fontWeight: 600,
              opacity: loading ? 0.5 : 1,
            }}
          >
            Move{fileList.length > 0 ? ' + update links' : ''}
          </button>
          <button
            onClick={() => onConfirm(false)}
            disabled={loading}
            style={{
              padding: '5px 12px',
              background: 'transparent',
              color: 'var(--text-muted)',
              border: '1px solid var(--border)',
              borderRadius: 4,
              cursor: loading ? 'not-allowed' : 'pointer',
              fontSize: 12,
              opacity: loading ? 0.5 : 1,
            }}
          >
            Move only
          </button>
          <button
            onClick={onCancel}
            style={{
              padding: '5px 12px',
              background: 'transparent',
              color: 'var(--text-muted)',
              border: '1px solid var(--border)',
              borderRadius: 4,
              cursor: 'pointer',
              fontSize: 12,
              marginLeft: 'auto',
            }}
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  )
}
