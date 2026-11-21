interface SpinnerProps {
  size?: 'sm' | 'md' | 'lg'
  label?: string
}

export function Spinner({ size = 'md', label }: SpinnerProps) {
  const cls = size === 'sm' ? 'spinner spinner--sm' : size === 'lg' ? 'spinner spinner--lg' : 'spinner'
  return (
    <span
      style={{ display: 'inline-flex', alignItems: 'center', gap: 'var(--space-2)' }}
      aria-label={label ?? 'Loading'}
      role="status"
    >
      <span className={cls} aria-hidden="true" />
      {label && (
        <span style={{ fontSize: 'var(--text-sm)', color: 'var(--text-muted)' }}>
          {label}
        </span>
      )}
    </span>
  )
}
