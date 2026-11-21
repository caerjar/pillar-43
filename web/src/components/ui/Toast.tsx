import { ReactNode, createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { TOAST_DURATION_MS } from '../../constants'
import { generateUUID } from '../../lib/uuid'

export type ToastTone = 'info' | 'success' | 'warning' | 'error'

interface ToastInput {
  message: ReactNode
  tone?: ToastTone
  /** Override default duration. Pass 0 for persistent (manual dismiss only). */
  duration?: number
}

interface Toast extends ToastInput {
  id: string
}

type ToastFn = (input: ToastInput | string) => void

interface ToastApi {
  toast: ToastFn
  success: (msg: ReactNode, opts?: Partial<ToastInput>) => void
  error: (msg: ReactNode, opts?: Partial<ToastInput>) => void
  warning: (msg: ReactNode, opts?: Partial<ToastInput>) => void
  info: (msg: ReactNode, opts?: Partial<ToastInput>) => void
}

const ToastContext = createContext<ToastApi | null>(null)

const TONE_COLORS: Record<ToastTone, { bg: string; text: string; border: string }> = {
  info: {
    bg: 'var(--bg-panel, var(--bg-base))',
    text: 'var(--text-primary)',
    border: 'var(--border)',
  },
  success: {
    bg: 'var(--bg-panel, var(--bg-base))',
    text: 'var(--success, #4caf50)',
    border: 'var(--success, #4caf50)',
  },
  warning: {
    bg: 'var(--bg-panel, var(--bg-base))',
    text: 'var(--warning, #ff9800)',
    border: 'var(--warning, #ff9800)',
  },
  error: {
    bg: 'var(--bg-panel, var(--bg-base))',
    text: 'var(--error, #c0392b)',
    border: 'var(--error, #c0392b)',
  },
}

function ToastItem({ toast, onDismiss }: { toast: Toast; onDismiss: () => void }) {
  const colors = TONE_COLORS[toast.tone ?? 'info']
  const duration = toast.duration ?? TOAST_DURATION_MS

  useEffect(() => {
    if (duration <= 0) return
    const t = setTimeout(onDismiss, duration)
    return () => clearTimeout(t)
  }, [duration, onDismiss])

  return (
    <div
      role="status"
      style={{
        background: colors.bg,
        color: colors.text,
        border: `1px solid ${colors.border}`,
        borderRadius: 4,
        padding: '10px 14px',
        fontSize: 13,
        boxShadow: '0 4px 16px rgba(0, 0, 0, 0.3)',
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        minWidth: 280,
        maxWidth: 460,
        animation: 'toast-slide-in 200ms ease-out',
      }}
    >
      <div style={{ flex: 1 }}>{toast.message}</div>
      <button
        onClick={onDismiss}
        aria-label="Dismiss"
        style={{
          background: 'transparent',
          border: 'none',
          color: 'inherit',
          cursor: 'pointer',
          fontSize: 16,
          lineHeight: 1,
          opacity: 0.6,
          padding: 0,
        }}
      >
        ✕
      </button>
    </div>
  )
}

/**
 * Wrap the App in <ToastProvider> once. Use the hook anywhere.
 */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])

  const dismiss = useCallback((id: string) => {
    setToasts((ts) => ts.filter((t) => t.id !== id))
  }, [])

  const toast: ToastFn = useCallback((input) => {
    const t: Toast =
      typeof input === 'string'
        ? { id: generateUUID(), message: input, tone: 'info' }
        : { id: generateUUID(), tone: 'info', ...input }
    setToasts((ts) => [...ts, t])
  }, [])

  // Memoised, and the variants with it. This object is the context value, and
  // it was a fresh literal on every render of the provider — so every consumer
  // of useToast() re-rendered whenever ANY toast appeared or dismissed, and
  // `error`/`success`/… had a new identity each time. That made them unusable
  // as hook dependencies: adding one to a useCallback deps array would have
  // defeated the memo it was supposed to feed. `toast` is already stable
  // (useCallback with [] above), so everything here is stable for the
  // provider's lifetime.
  const api: ToastApi = useMemo(
    () => ({
      toast,
      success: (msg, opts) => toast({ ...opts, message: msg, tone: 'success' }),
      error: (msg, opts) => toast({ ...opts, message: msg, tone: 'error' }),
      warning: (msg, opts) => toast({ ...opts, message: msg, tone: 'warning' }),
      info: (msg, opts) => toast({ ...opts, message: msg, tone: 'info' }),
    }),
    [toast],
  )

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div
        aria-live="polite"
        style={{
          position: 'fixed',
          bottom: 20,
          right: 20,
          display: 'flex',
          flexDirection: 'column',
          gap: 8,
          zIndex: 1100,
          pointerEvents: 'none',
        }}
      >
        {toasts.map((t) => (
          <div key={t.id} style={{ pointerEvents: 'auto' }}>
            <ToastItem toast={t} onDismiss={() => dismiss(t.id)} />
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}

/**
 * Show a non-blocking toast notification.
 *
 *   const { toast, error } = useToast()
 *   error('Move failed: file is read-only')
 *   toast({ message: 'Saved.', tone: 'success' })
 *
 * Falls back to console logging if no <ToastProvider> is mounted (test contexts).
 */
export function useToast(): ToastApi {
  const ctx = useContext(ToastContext)
  if (!ctx) {
    const log = (level: ToastTone, msg: ReactNode) => {
      const text = typeof msg === 'string' ? msg : '[toast]'
      const fn = level === 'error' ? console.error : level === 'warning' ? console.warn : console.log
      fn(`[${level}]`, text)
    }
    const fallback: ToastFn = (input) => {
      const t = typeof input === 'string' ? { message: input, tone: 'info' as ToastTone } : input
      log(t.tone ?? 'info', t.message)
    }
    return {
      toast: fallback,
      success: (msg) => log('success', msg),
      error: (msg) => log('error', msg),
      warning: (msg) => log('warning', msg),
      info: (msg) => log('info', msg),
    }
  }
  return ctx
}
