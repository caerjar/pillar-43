import { CSSProperties, ReactNode, ButtonHTMLAttributes } from 'react'

export type ButtonVariant = 'primary' | 'ghost' | 'destructive' | 'subtle'
export type ButtonSize = 'sm' | 'md'

interface Props extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'size'> {
  variant?: ButtonVariant
  size?: ButtonSize
  loading?: boolean
  leftIcon?: ReactNode
  rightIcon?: ReactNode
  children?: ReactNode
}

const SIZE_STYLES: Record<ButtonSize, CSSProperties> = {
  sm: { padding: '2px 8px', fontSize: 11, borderRadius: 3, height: 22 },
  md: { padding: '6px 12px', fontSize: 13, borderRadius: 4, height: 30 },
}

const VARIANT_STYLES: Record<ButtonVariant, CSSProperties> = {
  primary: {
    background: 'var(--accent)',
    color: 'var(--bg-base, #1a1714)',
    border: '1px solid var(--accent)',
  },
  ghost: {
    background: 'transparent',
    color: 'var(--accent)',
    border: '1px solid var(--accent)',
  },
  destructive: {
    background: 'transparent',
    color: 'var(--error, #c0392b)',
    border: '1px solid var(--error, #c0392b)',
  },
  subtle: {
    background: 'transparent',
    color: 'var(--text-secondary)',
    border: '1px solid var(--border)',
  },
}

/**
 * Standard button. Use over inline `<button style={...}>` for consistent
 * sizing, hover state, and disabled handling.
 *
 *   <Button variant="primary">Save</Button>
 *   <Button variant="destructive" onClick={...}>Delete</Button>
 *   <Button variant="ghost" size="sm" loading={saving}>Run</Button>
 */
export function Button({
  variant = 'ghost',
  size = 'md',
  loading = false,
  leftIcon,
  rightIcon,
  disabled,
  style,
  children,
  ...rest
}: Props) {
  const isDisabled = disabled || loading
  return (
    <button
      {...rest}
      disabled={isDisabled}
      style={{
        ...SIZE_STYLES[size],
        ...VARIANT_STYLES[variant],
        cursor: isDisabled ? 'default' : 'pointer',
        opacity: isDisabled ? 0.5 : 1,
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 6,
        fontFamily: 'inherit',
        whiteSpace: 'nowrap',
        transition: 'opacity 150ms, background 150ms',
        ...style,
      }}
    >
      {leftIcon}
      {loading ? <span aria-hidden>…</span> : children}
      {rightIcon}
    </button>
  )
}
