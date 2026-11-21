/**
 * The title-file timeline shared by Explore and People: one row per title plus
 * Press, years along the bottom, a dot per document at its date. Every dot is
 * a real button with its full description as its name; nothing here depends on
 * hover. Empty years are blank, and there is no zoom or pan.
 */
import { useEffect, useRef, useState } from 'react'
import { muted } from '../styles'
import { axisTicks, formatDate, layoutRows, type TimelineRowIn } from './layout'

export interface TimelineItem {
  n: number
  name: string
  date?: string | null
  year?: number | null
  /** How the document got here: how it matched, or how it connects. */
  how: string
}

const SIDE = 12 // half the 24 px dot target

function useWidth(): [React.RefObject<HTMLDivElement>, number] {
  const ref = useRef<HTMLDivElement>(null)
  const [w, setW] = useState(800)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    setW(el.clientWidth || 800)
    if (typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(() => setW(el.clientWidth || 800))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  return [ref, w]
}

export function Timeline({ rows, items, selected, onSelect, registerDot, label }: {
  rows: TimelineRowIn[]
  items: TimelineItem[]
  selected: number | null
  onSelect: (n: number) => void
  registerDot: (key: string, el: HTMLButtonElement | null) => void
  label: string
}) {
  const [ref, width] = useWidth()
  const inner = Math.max(1, width - 2 * SIDE)
  const layout = layoutRows(rows, items, inner)
  const byN = new Map(items.map((i) => [i.n, i]))
  const ticks = layout.scale ? axisTicks(layout.scale, items, inner) : []
  return (
    <div ref={ref} role="group" aria-label={label} style={{ maxWidth: 960 }}>
      {layout.rows.map((r, ri) => (
        <div key={`${r.key}-${ri}`} style={{ marginBottom: 6 }}>
          <div style={{ fontSize: 'var(--text-sm)', color: 'var(--text-primary)', fontWeight: r.isPress ? 400 : 600 }}>
            {r.label}
          </div>
          <div
            style={{
              position: 'relative', height: r.lanes * 28 + 4,
              borderBottom: '1px solid var(--border-subtle)',
            }}
          >
            {r.dots.map((d) => {
              const it = byN.get(d.n)!
              const on = selected === d.n
              const date = formatDate(it.date, it.year)
              return (
                <button
                  key={d.n}
                  type="button"
                  ref={(el) => registerDot(`${ri}:${d.n}`, el)}
                  data-dot={d.n}
                  aria-label={`${it.name}, ${date}, ${it.how}`}
                  aria-pressed={on}
                  onClick={() => onSelect(d.n)}
                  style={{
                    position: 'absolute', top: d.lane * 28 + 2,
                    left: `calc(${SIDE}px + (100% - ${2 * SIDE}px) * ${d.x})`,
                    transform: 'translateX(-50%)',
                    width: 24, height: 24, padding: 0, background: 'none', border: 'none',
                    cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center',
                  }}
                >
                  <span
                    aria-hidden="true"
                    style={{
                      width: on ? 14 : 10, height: on ? 14 : 10, borderRadius: '50%',
                      background: 'var(--accent)',
                      outline: on ? '2px solid var(--text-primary)' : 'none', outlineOffset: 1,
                    }}
                  />
                </button>
              )
            })}
            {r.dots.length === 0 && <span style={{ ...muted, position: 'absolute', left: 0, top: 6 }}>No documents</span>}
          </div>
        </div>
      ))}
      {layout.scale && (
        <div aria-hidden="true" style={{ position: 'relative', height: '1.6em', ...muted }}>
          {ticks.map((t) => (
            <span
              key={t.year}
              style={{
                position: 'absolute', transform: 'translateX(-50%)',
                left: `calc(${SIDE}px + (100% - ${2 * SIDE}px) * ${t.x})`, whiteSpace: 'nowrap',
              }}
            >
              {t.year}
            </span>
          ))}
        </div>
      )}
      {layout.undated.length > 0 && (
        <div style={{ ...muted, marginTop: 8 }}>
          Undated:{' '}
          {layout.undated.map((n) => {
            const it = byN.get(n)!
            return (
              <button
                key={n}
                type="button"
                ref={(el) => registerDot(`u:${n}`, el)}
                aria-label={`${it.name}, undated, ${it.how}`}
                onClick={() => onSelect(n)}
                style={{ minHeight: 24, background: 'none', border: 'none', cursor: 'pointer', color: 'var(--accent-text)', fontFamily: 'inherit', fontSize: 'inherit' }}
              >
                {it.name}
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}

/** Focus the first rendered dot for `n`. */
export function focusDot(refs: Map<string, HTMLButtonElement>, n: number) {
  for (const [k, el] of refs) {
    if (k.endsWith(`:${n}`)) { el.focus(); return }
  }
}
