import { useEffect, useRef } from 'react'
import { useAppStore } from '../stores/appStore'
import { useToast } from '../components/ui/Toast'

/**
 * Surfaces a structured toast when the global store catches a classified
 * backend error from any AI call (catalog passes, /api/ai/* streams,
 * regen, librarian, etc.).
 *
 * Wire-up:
 *   - The SSE consumers (useSSEStream, MaintainPanel.runFeature, etc.)
 *     detect events with `error_code` and call setLastError(...).
 *   - This hook subscribes to lastError and routes by code → toast tone +
 *     duration + (optional) CTA.
 *   - Toasts are dismissed via X button, by clicking the CTA (which clears
 *     lastError so it doesn't re-fire), or by timeout for non-sticky codes.
 *
 * Mount this hook once near the top of the React tree (App.tsx Layout).
 * Mounting multiple times would fire duplicate toasts for the same error.
 *
 * Replaces the older `useBillingAlert` from W4 (billing-exhausted only).
 * Adding a new error_code = add an entry to ERROR_DISPLAY below.
 */
type ToastTone = 'info' | 'success' | 'warning' | 'error'

interface ErrorDisplay {
  tone: ToastTone
  sticky: boolean
  /** Optional inline action button: label + which Settings group to open.
   *  `section` is a group id from `Settings/groups.tsx`. Settings became a
   *  window on 2026-08-30, so this no longer names a left tab — and every one
   *  of these three codes is about the AI provider, so they land on that group
   *  rather than at the top of Preferences. */
  cta?: { label: string; section: string }
}

/**
 * Per-code display rules. Codes not listed fall through to a generic error
 * toast with no CTA.
 *
 *   - `billing_exhausted`: sticky, opens Settings to top up / change model.
 *   - `authentication_error`: sticky, opens Settings to fix API key.
 *   - `model_not_found_error`: sticky, opens Settings to pick a valid model.
 *   - `rate_limit_error`: auto-dismissing warning; retry is automatic.
 *   - `provider_connection_error`: sticky error; user action depends on env.
 */
const ERROR_DISPLAY: Record<string, ErrorDisplay> = {
  billing_exhausted: {
    tone: 'error',
    sticky: true,
    cta: { label: 'Open Settings', section: 'ai' },
  },
  authentication_error: {
    tone: 'error',
    sticky: true,
    cta: { label: 'Open Settings', section: 'ai' },
  },
  model_not_found_error: {
    tone: 'error',
    sticky: true,
    cta: { label: 'Open Settings', section: 'ai' },
  },
  rate_limit_error: {
    tone: 'warning',
    sticky: false,
  },
  provider_connection_error: {
    tone: 'error',
    sticky: true,
  },
}

export function useStructuredErrorAlert(): void {
  const lastError = useAppStore((s) => s.lastError)
  const clearLastError = useAppStore((s) => s.clearLastError)
  const openSettings = useAppStore((s) => s.openSettings)
  const toast = useToast()

  // De-dupe — if the same error fires twice in a row (e.g. two SSE consumers
  // both see the same backend event), we only show one toast.
  const lastShownRef = useRef<string | null>(null)

  useEffect(() => {
    if (!lastError) {
      lastShownRef.current = null
      return
    }
    const display = ERROR_DISPLAY[lastError.code]
    if (!display) return

    const key = `${lastError.code}:${lastError.message}`
    if (lastShownRef.current === key) return
    lastShownRef.current = key

    const openGroup = (section: string) => () => {
      openSettings(section)
      clearLastError()
    }

    const content = display.cta ? (
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 12 }}>
        <span>{lastError.message}</span>
        <button
          type="button"
          onClick={openGroup(display.cta.section)}
          style={{
            background: 'transparent',
            border: '1px solid var(--error, #c0392b)',
            color: 'var(--error, #c0392b)',
            borderRadius: 3,
            padding: '4px 10px',
            fontSize: 12,
            fontWeight: 600,
            cursor: 'pointer',
          }}
        >
          {display.cta.label}
        </button>
      </span>
    ) : (
      <span>{lastError.message}</span>
    )

    const opts = display.sticky ? { duration: 0 } : undefined
    if (display.tone === 'error') {
      toast.error(content, opts)
    } else if (display.tone === 'warning') {
      toast.warning(content, opts)
    } else if (display.tone === 'success') {
      toast.success(content, opts)
    } else {
      toast.info(content, opts)
    }
  }, [lastError, toast, openSettings, clearLastError])
}

// Backwards-compat alias. The hook was renamed from `useBillingAlert` when
// the error_code routing was generalized beyond billing-exhausted. Existing
// callers can keep the old name; new code should use `useStructuredErrorAlert`.
export const useBillingAlert = useStructuredErrorAlert
