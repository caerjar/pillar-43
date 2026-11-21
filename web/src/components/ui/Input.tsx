import { CSSProperties, InputHTMLAttributes } from 'react'

export type InputSize = 'sm' | 'md'
export type InputType = 'text' | 'number' | 'search'

export interface InputProps
  extends Omit<InputHTMLAttributes<HTMLInputElement>, 'size' | 'onChange' | 'value' | 'type'> {
  value: string
  onChange: (value: string) => void
  type?: InputType
  placeholder?: string
  size?: InputSize
  disabled?: boolean
  ariaLabel?: string
  className?: string
  autoFocus?: boolean
}

const SIZE_STYLES: Record<InputSize, CSSProperties> = {
  sm: { padding: '2px 6px', fontSize: 11, borderRadius: 3, height: 22 },
  md: { padding: '6px 10px', fontSize: 13, borderRadius: 4, height: 30 },
}

/**
 * Standard <input> wrapper. Use over inline `<input style={...}>` for
 * consistent sizing, focus ring, and disabled handling.
 *
 *   <Input value={dest} onChange={setDest} placeholder="notes/folder/file.md" />
 *   <Input type="search" value={q} onChange={setQ} ariaLabel="Search threads" />
 */
export function Input({
  value,
  onChange,
  type = 'text',
  placeholder,
  size = 'md',
  disabled = false,
  ariaLabel,
  className,
  autoFocus,
  style,
  ...rest
}: InputProps) {
  return (
    <input
      {...rest}
      type={type}
      value={value}
      placeholder={placeholder}
      disabled={disabled}
      aria-label={ariaLabel}
      className={className}
      autoFocus={autoFocus}
      onChange={(e) => onChange(e.target.value)}
      style={{
        ...SIZE_STYLES[size],
        background: 'var(--bg-base)',
        color: 'var(--text-secondary)',
        border: '1px solid var(--border)',
        cursor: disabled ? 'default' : 'text',
        opacity: disabled ? 0.5 : 1,
        fontFamily: 'inherit',
        outline: 'none',
        minWidth: 0,
        transition: 'border-color 150ms, opacity 150ms',
        ...style,
      }}
    />
  )
}
