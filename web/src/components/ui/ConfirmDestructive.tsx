import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { Modal } from './Modal'

/**
 * Type-to-confirm, for actions an "Are you sure?" is too cheap for.
 *
 * `Confirm.tsx` covers the ordinary destructive case (Move to Trash) and its
 * `ConfirmFn` type is deliberately left alone: `CommandCtx.confirm` is typed
 * against it, so widening it would give every menu action a shape it does not
 * need. This is a separate primitive for a separate severity.
 *
 * What it buys: the confirm button stays disabled until the exact phrase is
 * typed, so the action cannot be reached by muscle memory, a stray Enter, or a
 * click on a dialog that appeared where the last one did.
 */
export interface ConfirmDestructiveOptions {
  title: string
  message: ReactNode
  /** What survives. Rendered as a list, because it is the reassuring half. */
  kept?: string[]
  /** What does not. Rendered as a list, because it is the irreversible half. */
  removed?: string[]
  /** Exact, case-sensitive phrase the user must type. */
  phrase: string
  confirmLabel?: string
}

type ConfirmDestructiveFn = (opts: ConfirmDestructiveOptions) => Promise<boolean>

const noop: ConfirmDestructiveFn = () => Promise.resolve(false)
const Ctx = createContext<ConfirmDestructiveFn>(noop)

/** Module-level default so consumers get a stable reference with no provider. */
export function useConfirmDestructive(): ConfirmDestructiveFn {
  return useContext(Ctx)
}

export function ConfirmDestructiveProvider({ children }: { children: ReactNode }) {
  const [opts, setOpts] = useState<ConfirmDestructiveOptions | null>(null)
  const [typed, setTyped] = useState('')
  const resolveRef = useRef<((v: boolean) => void) | null>(null)

  const confirm = useCallback<ConfirmDestructiveFn>((next) => {
    setOpts(next)
    setTyped('')
    return new Promise<boolean>((resolve) => {
      resolveRef.current = resolve
    })
  }, [])

  const settle = useCallback((value: boolean) => {
    resolveRef.current?.(value)
    resolveRef.current = null
    setOpts(null)
    setTyped('')
  }, [])

  // Exact and case-sensitive. Trimmed only at the edges, so a trailing space
  // from a paste is forgiven while "erase" is not.
  const armed = opts !== null && typed.trim() === opts.phrase

  const value = useMemo(() => confirm, [confirm])

  return (
    <Ctx.Provider value={value}>
      {children}
      {opts !== null && createPortal(
        <Modal open onClose={() => settle(false)} title={opts.title} width={520}>
          <div style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.6 }}>
            {opts.message}
          </div>

          {opts.removed && opts.removed.length > 0 && (
            <div style={{ marginTop: 14 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--error)', marginBottom: 4 }}>
                Deleted, permanently
              </div>
              <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12, color: 'var(--text-secondary)' }}>
                {opts.removed.map((r) => <li key={r}>{r}</li>)}
              </ul>
            </div>
          )}

          {opts.kept && opts.kept.length > 0 && (
            <div style={{ marginTop: 14 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 4 }}>
                Kept
              </div>
              <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12, color: 'var(--text-secondary)' }}>
                {opts.kept.map((k) => <li key={k}>{k}</li>)}
              </ul>
            </div>
          )}

          <label
            htmlFor="confirm-destructive-phrase"
            style={{ display: 'block', fontSize: 12, color: 'var(--text-secondary)', margin: '18px 0 6px' }}
          >
            Type <strong style={{ color: 'var(--text-primary)' }}>{opts.phrase}</strong> to continue
          </label>
          <input
            id="confirm-destructive-phrase"
            autoFocus
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && armed) settle(true) }}
            className="sp-input"
            style={{ width: '100%', boxSizing: 'border-box' }}
          />

          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 20 }}>
            <button
              onClick={() => settle(false)}
              style={{
                padding: '8px 16px', borderRadius: 6, fontSize: 13, cursor: 'pointer',
                border: '1px solid var(--border)', background: 'transparent', color: 'var(--text-secondary)',
              }}
            >
              Cancel
            </button>
            <button
              disabled={!armed}
              onClick={() => settle(true)}
              style={{
                padding: '8px 16px', borderRadius: 6, fontSize: 13,
                cursor: armed ? 'pointer' : 'not-allowed',
                border: 'none',
                background: armed ? 'var(--error)' : 'var(--bg-active)',
                color: armed ? 'var(--on-accent)' : 'var(--text-muted)',
                fontWeight: 600,
              }}
            >
              {opts.confirmLabel ?? 'Confirm'}
            </button>
          </div>
        </Modal>,
        document.body,
      )}
    </Ctx.Provider>
  )
}
