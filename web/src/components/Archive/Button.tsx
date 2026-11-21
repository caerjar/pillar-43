/**
 * The one button of the org views: primary (the main act on a screen), plain
 * (everything else) and destructive (an act that cannot be taken back). One
 * height, never under the 24 px target. Colours are tokens, and text on the
 * accent uses --on-accent, which passes 4.5:1 in both themes.
 */
import type { ButtonHTMLAttributes, CSSProperties } from 'react'

export type ArchiveButtonVariant = 'primary' | 'plain' | 'destructive'

const VARIANT: Record<ArchiveButtonVariant, CSSProperties> = {
  primary: { background: 'var(--accent)', color: 'var(--on-accent)', border: '1px solid var(--accent)' },
  plain: { background: 'transparent', color: 'var(--text-primary)', border: '1px solid var(--border)' },
  destructive: { background: 'transparent', color: 'var(--error)', border: '1px solid var(--error)' },
}

/** A disabled button is still a button: the same shape and border, muted. */
const DISABLED: CSSProperties = {
  background: 'var(--bg-surface)', color: 'var(--text-muted)', border: '1px solid var(--border)',
}

export function Button({
  variant = 'plain', style, type = 'button', ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ArchiveButtonVariant }) {
  return (
    <button
      type={type}
      {...rest}
      style={{
        minHeight: 28, minWidth: 28, boxSizing: 'border-box', padding: '2px 12px',
        fontFamily: 'inherit', fontSize: 'var(--text-sm)', borderRadius: 4,
        cursor: rest.disabled ? 'not-allowed' : 'pointer',
        ...VARIANT[variant], ...(rest.disabled ? DISABLED : {}), ...style,
      }}
    />
  )
}
