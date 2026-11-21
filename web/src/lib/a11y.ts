/**
 * Keyboard affordances for elements that aren't natively focusable.
 *
 * A `<div onClick>` is invisible to keyboard and screen-reader users: it takes
 * no focus, announces no role, and never fires on Enter or Space. The codebase
 * had 53 of them against 4 `tabIndex` attributes in total.
 *
 * **Prefer a real `<button>`.** It gets focus, role, keyboard activation,
 * and the platform's focus ring for free. Reach for `clickable()` only when a
 * button is genuinely wrong — a table row, a tree node, a card whose content
 * includes its own nested controls (a button inside a button is invalid HTML
 * and browsers will re-parent it).
 */
import type { KeyboardEvent, MouseEvent } from 'react'

/**
 * Props that make a non-button element behave like one.
 *
 * Enter and Space both activate, matching native button behaviour. Space is
 * `preventDefault`ed because its default action is to scroll the page.
 *
 * The handler ignores events that bubbled up from a nested control, so a row
 * containing its own buttons doesn't fire twice when one of them is used.
 */
export function clickable(
  onActivate: (e: MouseEvent | KeyboardEvent) => void,
  opts: { label?: string; disabled?: boolean; role?: string } = {},
) {
  const { label, disabled, role = 'button' } = opts
  return {
    // Overridable: some call sites are a menuitem or an option, not a button.
    role,
    tabIndex: disabled ? -1 : 0,
    'aria-label': label,
    'aria-disabled': disabled || undefined,
    // The event is forwarded so handlers that need stopPropagation — an
    // action nested inside another clickable row — keep working unchanged.
    onClick: disabled ? undefined : (e: MouseEvent) => onActivate(e),
    onKeyDown: disabled
      ? undefined
      : (e: KeyboardEvent) => {
          if (e.key !== 'Enter' && e.key !== ' ') return
          // Fired from a nested button/input/link — let that own the event.
          if (e.target !== e.currentTarget) return
          e.preventDefault()
          e.stopPropagation()
          onActivate(e)
        },
  }
}

/**
 * Marks a click target that exists purely as a mouse convenience, where the
 * keyboard path is elsewhere and equivalent.
 *
 * The canonical case is a modal backdrop: clicking it dismisses, and so does
 * Escape. Giving the backdrop a tab stop would be actively worse — it adds a
 * focusable element that announces nothing and traps nobody.
 *
 * `role="presentation"` says exactly that: this node carries no semantics of
 * its own. Do NOT use it to silence a control that has no keyboard path at
 * all; that is the lint finding being real.
 */
export const dismissTarget = { role: 'presentation' as const }
