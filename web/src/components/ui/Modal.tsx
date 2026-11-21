import { CSSProperties, ReactNode, useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'

interface Props {
  open: boolean
  onClose: () => void
  title?: ReactNode
  children?: ReactNode
  /** Width in px or any CSS length. Default 480px. */
  width?: number | string
  /** Close on backdrop click. Default true. */
  closeOnBackdrop?: boolean
  /** Close on Escape. Default true. */
  closeOnEscape?: boolean
  /** ARIA describedby region inside the modal body. */
  ariaDescribedBy?: string
  /** Body padding. Default 16. Pass 0 for a dialog that owns its own layout. */
  bodyPadding?: number | string
  /** Extra style on the dialog box itself (height, display, …). */
  contentStyle?: CSSProperties
}

const FOCUSABLE = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',')

/**
 * Generic modal with focus trap, Escape, backdrop click, and portal mount.
 *
 *   <Modal open={open} onClose={() => setOpen(false)} title="Confirm">
 *     <p>...</p>
 *     <Button onClick={...}>OK</Button>
 *   </Modal>
 */
export function Modal({
  open,
  onClose,
  title,
  children,
  width = 480,
  closeOnBackdrop = true,
  closeOnEscape = true,
  ariaDescribedBy,
  bodyPadding = 16,
  contentStyle,
}: Props) {
  const dialogRef = useRef<HTMLDivElement>(null)
  const returnFocusTo = useRef<Element | null>(null)

  // Escape to close
  useEffect(() => {
    if (!open || !closeOnEscape) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation()
        onClose()
      }
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [open, closeOnEscape, onClose])

  // Focus the dialog when it opens, and restore focus to whatever the user was
  // on when it closes.
  useEffect(() => {
    if (!open) return
    returnFocusTo.current = document.activeElement
    const t = setTimeout(() => dialogRef.current?.focus(), 0)
    return () => {
      clearTimeout(t)
      const prev = returnFocusTo.current
      if (prev instanceof HTMLElement && document.contains(prev)) prev.focus()
    }
  }, [open])

  // Focus trap. The docstring below promised one from the beginning and the
  // implementation only ever focused the dialog once — so Tab walked straight
  // out into the application behind an `aria-modal="true"` dialog, which is
  // exactly the claim that attribute makes to a screen reader.
  //
  // Capture phase, because a child (CodeMirror, a listbox) may handle Tab
  // itself; the trap has to see it first to know whether it is the edge.
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Tab') return
      const root = dialogRef.current
      if (!root) return
      const items = Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE))
        .filter((el) => el.offsetParent !== null || el === document.activeElement)
      if (items.length === 0) {
        // Nothing focusable inside: keep focus on the dialog rather than
        // letting it escape to the page behind.
        e.preventDefault()
        root.focus()
        return
      }
      const first = items[0]
      const last = items[items.length - 1]
      const active = document.activeElement
      if (!e.shiftKey && (active === last || !root.contains(active))) {
        e.preventDefault()
        first.focus()
      } else if (e.shiftKey && (active === first || active === root || !root.contains(active))) {
        e.preventDefault()
        last.focus()
      }
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [open])

  if (!open) return null

  return createPortal(
    <div
      // role="presentation" is what makes the backdrop's dismiss-on-click
      // acceptable: it carries no semantics, and Escape already closes the
      // dialog, so there is no keyboard path missing here.
      role="presentation"
      onClick={closeOnBackdrop ? onClose : undefined}
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0, 0, 0, 0.5)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1000,
        animation: 'modal-fade-in 150ms ease-out',
      }}
    >
      {/* The onClick below only stops propagation so a click inside the
          dialog doesn't reach the backdrop's dismiss handler. It is not a
          user affordance, so there is nothing for a keyboard user to invoke. */}
      {/* eslint-disable-next-line jsx-a11y/click-events-have-key-events */}
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label={typeof title === 'string' ? title : undefined}
        aria-describedby={ariaDescribedBy}
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
        style={{
          width: typeof width === 'number' ? `${width}px` : width,
          maxWidth: 'calc(100vw - 32px)',
          maxHeight: 'calc(100vh - 64px)',
          overflow: 'auto',
          background: 'var(--bg-panel, var(--bg-base))',
          color: 'var(--text-primary)',
          border: '1px solid var(--border)',
          borderRadius: 6,
          boxShadow: '0 12px 48px rgba(0, 0, 0, 0.4)',
          padding: 0,
          outline: 'none',
          ...contentStyle,
        }}
      >
        {title && (
          <div
            style={{
              padding: '12px 16px',
              borderBottom: '1px solid var(--border)',
              fontSize: 14,
              fontWeight: 600,
            }}
          >
            {title}
          </div>
        )}
        <div style={{ padding: bodyPadding }}>{children}</div>
      </div>
    </div>,
    document.body,
  )
}
