/**
 * My work: the writer's own items as one table. The backend decides which
 * items come back; this view renders them and never widens them.
 *
 * Per row: the item's title, its level (private / staff / model, each written
 * out with what it means), the label notices on it in plain words, the dated
 * record of every time the AI read it, and withdraw with its confirm written
 * in place. No dialogs, no icons standing in for consent.
 */
import { useState, type CSSProperties } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  fetchMyWork, setItemConsent, setItemLabels, withdrawItem,
  type ConsentLevel, type LabelNotice, type MyWorkItem,
} from '../../../lib/api/archive'
import { errorMessage } from '../../../lib/errors'
import { Button } from '../Button'
import { muted } from '../styles'

export const LEVELS: { id: ConsentLevel; name: string; meaning: string }[] = [
  { id: 'private', name: 'Private', meaning: 'Held in the archive. Nobody searches it, and the AI never reads it.' },
  { id: 'staff', name: 'Staff', meaning: 'Staff can search and cite it. The AI never reads it.' },
  { id: 'model', name: 'Model', meaning: 'The AI may read it to answer staff questions.' },
]

const cell: CSSProperties = {
  padding: '12px 12px 12px 0', verticalAlign: 'top', textAlign: 'left',
  borderBottom: '1px solid var(--border-subtle)', fontSize: 'var(--text-sm)',
}

const day = (iso: string) => iso.slice(0, 10)

/** Under 760 px the table becomes one block per item: each cell gets its
 *  column name above it, and the header row is read by screen readers only. */
const STACK_CSS = `
@media (max-width: 760px) {
  .terms-table, .terms-table tbody, .terms-table tr, .terms-table th, .terms-table td { display: block; min-width: 0 !important; }
  .terms-table thead { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
  .terms-table tr { border-bottom: 1px solid var(--border); padding-bottom: 8px; }
  .terms-table td::before { content: attr(data-label); display: block; font-size: var(--text-xs); color: var(--text-muted); font-weight: 600; margin-bottom: 2px; }
}`

export function TermsView() {
  const qc = useQueryClient()
  const { data, isLoading, error } = useQuery({ queryKey: ['my-work'], queryFn: ({ signal }) => fetchMyWork(signal), staleTime: 5_000 })
  const refresh = () => qc.invalidateQueries({ queryKey: ['my-work'] })

  if (isLoading) return <div role="status" style={{ padding: 32, ...muted }}>Loading your work…</div>
  if (error || !data) {
    return <div role="alert" style={{ padding: 32, color: 'var(--error)', fontSize: 'var(--text-sm)' }}>{errorMessage(error ?? new Error('No answer'))}</div>
  }
  return (
    <div data-testid="terms-view" style={{ flex: 1, minWidth: 0, overflow: 'auto', padding: '24px 32px' }}>
      <style>{STACK_CSS}</style>
      <h1 style={{ margin: '0 0 4px', fontSize: 'var(--text-lg)', fontWeight: 600, color: 'var(--text-primary)' }}>My work</h1>
      <p style={{ margin: '0 0 20px', maxWidth: 640, ...muted }}>
        Only your own items are listed. You decide what the archive and the AI may do with each one.
      </p>
      {data.items.length === 0 ? (
        <p style={{ fontSize: 'var(--text-sm)', color: 'var(--text-primary)' }}>No items are linked to your account yet.</p>
      ) : (
        <div role="region" aria-label="My work table" tabIndex={0} style={{ overflowX: 'auto' }}>
          <table className="terms-table" style={{ borderCollapse: 'collapse', width: '100%' }}>
            <thead>
              <tr>
                {['Item', 'Level', 'Labels', 'Read by the AI', 'Withdraw'].map((h) => (
                  <th key={h} scope="col" style={{ ...cell, ...muted, fontWeight: 600, borderBottom: '1px solid var(--border)' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.items.map((item) => (
                <Row key={item.path} item={item} options={data.label_options} onChanged={refresh} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function Row({ item, options, onChanged }: { item: MyWorkItem; options: LabelNotice[]; onChanged: () => void }) {
  const [confirming, setConfirming] = useState(false)
  const [problem, setProblem] = useState('')
  const withdrawn = item.withdrawn_at != null

  const act = useMutation({
    mutationFn: (fn: () => Promise<void>) => fn(),
    onSuccess: () => { setProblem(''); setConfirming(false); onChanged() },
    onError: (e) => setProblem(errorMessage(e)),
  })
  const ids = item.labels.map((l) => l.id)
  const setLabels = (next: string[]) => act.mutate(() => setItemLabels(item.path, next))
  const available = options.filter((o) => !ids.includes(o.id))

  return (
    <tr data-testid={`terms-row-${item.path}`}>
      <th scope="row" style={{ ...cell, fontWeight: 400, minWidth: 150 }}>
        <div style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{item.title}</div>
        <div style={muted}>{item.kind}</div>
        {withdrawn && <div style={{ marginTop: 6, color: 'var(--text-primary)' }}>Withdrawn on {day(item.withdrawn_at!)}</div>}
        {problem && <div role="alert" style={{ marginTop: 6, color: 'var(--error)', fontSize: 'var(--text-xs)' }}>{problem}</div>}
      </th>

      <td data-label="Level" style={{ ...cell, minWidth: 250 }}>
        <fieldset disabled={withdrawn || act.isPending} style={{ border: 'none', margin: 0, padding: 0 }}>
          <legend style={{ position: 'absolute', width: 1, height: 1, overflow: 'hidden', clip: 'rect(0 0 0 0)' }}>Level for {item.title}</legend>
          {LEVELS.map((l) => (
            <label key={l.id} style={{ display: 'flex', gap: 8, alignItems: 'flex-start', minHeight: 28, padding: '2px 0', cursor: withdrawn ? 'default' : 'pointer' }}>
              <input
                type="radio"
                name={`level-${item.path}`}
                checked={item.consent === l.id}
                onChange={() => act.mutate(() => setItemConsent(item.path, l.id))}
                style={{ marginTop: 4 }}
              />
              <span>
                <span style={{ color: 'var(--text-primary)', fontWeight: item.consent === l.id ? 600 : 400 }}>{l.name}</span>
                <span style={{ ...muted, display: 'block' }}>{l.meaning}</span>
              </span>
            </label>
          ))}
        </fieldset>
      </td>

      <td data-label="Labels" style={{ ...cell, minWidth: 260 }}>
        {item.labels.length === 0 && <div style={muted}>No labels.</div>}
        <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
          {item.labels.map((l) => (
            <li key={l.id} style={{ marginBottom: 8 }}>
              <div style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{l.name}</div>
              <div style={muted}>{l.meaning}</div>
              {l.aipref && <div style={muted}>AI preference: {l.aipref}</div>}
              {!withdrawn && (
                <Button style={{ marginTop: 4 }} disabled={act.isPending}
                  aria-label={`Remove label ${l.name} from ${item.title}`}
                  onClick={() => setLabels(ids.filter((x) => x !== l.id))}>
                  Remove
                </Button>
              )}
            </li>
          ))}
        </ul>
        {!withdrawn && available.length > 0 && (
          <div role="group" aria-label={`Add a label to ${item.title}`} style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {available.map((o) => (
              <div key={o.id}>
                <Button disabled={act.isPending}
                  aria-label={`Add label ${o.name} to ${item.title}`}
                  onClick={() => setLabels([...ids, o.id])}>
                  Add {o.name}
                </Button>
                <div style={muted}>{o.meaning}</div>
              </div>
            ))}
          </div>
        )}
      </td>

      <td data-label="Read by the AI" style={{ ...cell, minWidth: 250 }}>
        {item.reads.length === 0 ? (
          <div style={muted}>Not read by the AI.</div>
        ) : (
          <>
            <div style={{ color: 'var(--text-primary)' }}>
              {item.reads.length === 1 ? 'Read once' : `Read ${item.reads.length} times`}
            </div>
            <ol aria-label={`Access log for ${item.title}`} tabIndex={0} style={{ margin: '4px 0 0', padding: 0, listStyle: 'none', maxHeight: 140, overflowY: 'auto' }}>
              {item.reads.map((r) => (
                <li key={r.receipt} style={muted}>
                  <time dateTime={r.at}>{day(r.at)}</time>, {r.purpose}, answer receipt {r.receipt}
                </li>
              ))}
            </ol>
          </>
        )}
      </td>

      <td data-label="Withdraw" style={{ ...cell, minWidth: 190 }}>
        {withdrawn ? (
          <div style={{ color: 'var(--text-primary)' }}>Withdrawn</div>
        ) : confirming ? (
          <div role="group" aria-label={`Confirm withdrawing ${item.title}`}>
            <p style={{ margin: '0 0 6px', color: 'var(--text-primary)' }}>
              Withdraw {item.title}? The archive forgets it and cannot take it back.
            </p>
            <Button variant="destructive" style={{ marginRight: 6 }}
              disabled={act.isPending} onClick={() => act.mutate(() => withdrawItem(item.path))}>
              Yes, withdraw
            </Button>
            <Button onClick={() => setConfirming(false)}>Keep it</Button>
          </div>
        ) : (
          <Button aria-label={`Withdraw ${item.title}`} onClick={() => setConfirming(true)}>Withdraw</Button>
        )}
      </td>
    </tr>
  )
}
