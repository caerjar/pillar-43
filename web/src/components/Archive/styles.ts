import type { CSSProperties } from 'react'

/** The quiet line under a heading: one style for every org view. */
export const muted: CSSProperties = { color: 'var(--text-muted)', fontSize: 'var(--text-xs)' }

/** WCAG 2.5.8: every control is at least 24 x 24 CSS px. */
export const target: CSSProperties = { minHeight: 24, minWidth: 24, boxSizing: 'border-box' }
