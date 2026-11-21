/**
 * What the archive could not say, one plain line per kind of absence with its
 * count and reason, set beside the answer in the same type. Never an error or
 * warning colour. Every number comes from the response.
 */
import type { AskResponse } from '../../../lib/api/archive'
import { Button } from '../Button'
import { muted } from './styles'

function years(ys: number[]): string {
  const runs: number[][] = []
  for (const y of ys) {
    const last = runs[runs.length - 1]
    if (last && y === last[last.length - 1] + 1) last.push(y)
    else runs.push([y])
  }
  return runs.map((r) => (r.length === 1 ? `${r[0]}` : `${r[0]}–${r[r.length - 1]}`)).join(', ')
}

const items = (n: number) => (n === 1 ? '1 item' : `${n} items`)

/** One plain line per group of closed items, each saying who closed them. */
function closedLines(s: NonNullable<AskResponse['silences']>): { key: string; text: string }[] {
  const by = s.closed_by
  if (!by || by.writer + by.default + by.staff !== s.closed) {
    return s.closed > 0 ? [{ key: 'closed', text: `${items(s.closed)} closed to the AI` }] : []
  }
  const out: { key: string; text: string }[] = []
  if (by.writer) out.push({ key: 'closed-writer', text: `${items(by.writer)} closed by ${by.writer === 1 ? 'its writer' : 'their writers'}` })
  if (by.default) out.push({ key: 'closed-default', text: `${items(by.default)} closed by default (no one has opened ${by.default === 1 ? 'it' : 'them'} to the AI)` })
  if (by.staff) out.push({ key: 'closed-staff', text: `${items(by.staff)} closed by staff or an administrator` })
  return out
}

export function Silences({ r, onOpenFile }: { r: AskResponse; onOpenFile: (path: string) => void }) {
  const s = r.silences
  const lines: { key: string; text: string }[] = []
  if (s) lines.push(...closedLines(s))
  else if (r.withheld_from_ai > 0) lines.push({ key: 'closed', text: `${items(r.withheld_from_ai)} closed to the AI` })
  for (const c of s?.closed_named ?? []) lines.push({ key: `named-${c.path}`, text: `${c.title}: ${c.reason ?? 'closed'}` })
  if (s?.no_document) lines.push({ key: 'no-document', text: `There is no ${s.no_document.kind} for ${s.no_document.title} in the archive` })
  for (const n of s?.missing_correspondents ?? []) lines.push({ key: `from-${n}`, text: `${n}'s replies are not in the archive` })
  if (s && s.empty_years.length > 0) lines.push({ key: 'years', text: `Nothing from ${years(s.empty_years)}` })
  const staff = r.staff_only_sources
  return (
    <aside aria-label="Not in this answer" data-testid="silences" style={{ minWidth: 0 }}>
      <h2 style={{ margin: '0 0 6px', fontSize: 'var(--text-sm)', fontWeight: 600, color: 'var(--text-primary)' }}>
        Not in this answer
      </h2>
      <ul style={{ listStyle: 'none', margin: 0, padding: 0, fontSize: 'var(--text-sm)', lineHeight: 1.5, color: 'var(--text-primary)' }}>
        {lines.map((l) => <li key={l.key} style={{ marginBottom: 6 }}>{l.text}</li>)}
        {staff.length > 0 && (
          <li style={{ marginBottom: 6 }}>
            {staff.length === 1 ? '1 item at staff level, not read by the AI' : `${staff.length} items at staff level, not read by the AI`}
            <ul style={{ listStyle: 'none', margin: '2px 0 0', padding: 0 }}>
              {staff.map((x) => (
                <li key={x.path}>
                  <Button onClick={() => onOpenFile(x.path)}>
                    {x.title} <span style={muted}>{x.kind}</span>
                  </Button>
                </li>
              ))}
            </ul>
          </li>
        )}
        {lines.length === 0 && staff.length === 0 && (
          <li style={{ color: 'var(--text-secondary)' }}>No closed items, absent letters or empty years for this question.</li>
        )}
      </ul>
    </aside>
  )
}
