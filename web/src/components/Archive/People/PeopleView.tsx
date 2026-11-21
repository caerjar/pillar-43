/**
 * People: the people the catalog credits, then one person's record: name,
 * relationship to the press, titles, the same timeline with each dot saying
 * how the document connects, and a count of items not open to the AI.
 */
import { useEffect, useRef, useState } from 'react'
import { fetchPeople, fetchPersonRecord, type PersonSummary } from '../../../lib/api/archive'
import { errorMessage } from '../../../lib/errors'
import { muted } from '../styles'
import { dateRange } from '../Explore/layout'
import { useArchiveViews } from '../viewStore'
import { NotOpen, PassagePanel } from '../Explore/PassagePanel'
import { Timeline, type TimelineItem } from '../Explore/Timeline'


/** The full name and each word of it, longest first, to mark in a passage. */
function nameTerms(name: string): string[] {
  const words = name.split(/\s+/).filter((w) => w.length > 1)
  return [name, ...words]
}

export function PeopleView() {
  const { personName, person, personSelected, set } = useArchiveViews()
  const [people, setPeople] = useState<PersonSummary[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [listError, setListError] = useState<string | null>(null)
  const dotRefs = useRef(new Map<string, HTMLButtonElement>())

  useEffect(() => {
    const c = new AbortController()
    fetchPeople(c.signal).then(setPeople).catch((e) => { if (!c.signal.aborted) setListError(errorMessage(e)) })
    return () => c.abort()
  }, [])

  async function open(name: string) {
    set({ personName: name, person: null, personSelected: null })
    setError(null)
    try {
      set({ person: await fetchPersonRecord(name) })
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  const items: TimelineItem[] = (person?.items ?? []).map((i) => ({
    n: i.n, name: i.name, date: i.date, year: i.year, how: i.connections.join(' and '),
  }))
  const KINDS = ['signed', 'wrote', 'received', 'mentioned'] as const
  const kindCounts = KINDS.map((k) => ({
    kind: k, count: (person?.items ?? []).filter((i) => i.connections.includes(k)).length,
  })).filter((k) => k.count > 0)
  const range = dateRange(person?.first_date, person?.last_date)
  const selected = person?.items.find((i) => i.n === personSelected)

  return (
    <div data-testid="people-view" style={{ position: 'relative', flex: 1, display: 'flex', minHeight: 0, overflow: 'hidden' }}>
      <div style={{ flex: 1, minWidth: 0, overflowY: 'auto', padding: '24px 32px' }}>
        {error && <div role="alert" style={{ color: 'var(--error)', fontSize: 'var(--text-sm)', marginBottom: 12 }}>{error}</div>}
        {!people && !listError && <div role="status" style={{ ...muted, marginBottom: 12 }}>Loading people…</div>}
        {listError && (
          <div role="alert" style={{ color: 'var(--error)', fontSize: 'var(--text-sm)', marginBottom: 12 }}>
            The list of people could not be loaded. {listError}
          </div>
        )}

        <ul aria-label="People" style={{ listStyle: 'none', margin: '0 0 28px', padding: 0, maxWidth: 720 }}>
          {people?.map((p) => (
            <li key={p.name}>
              <button
                type="button"
                onClick={() => open(p.name)}
                aria-current={p.name === personName ? 'true' : undefined}
                style={{
                  display: 'block', width: '100%', minHeight: 28, padding: '2px 0', background: 'none', border: 'none',
                  cursor: 'pointer', fontFamily: 'inherit', textAlign: 'left', fontSize: 'var(--text-sm)',
                  color: p.name === personName ? 'var(--text-primary)' : 'var(--text-secondary)',
                  fontWeight: p.name === personName ? 600 : 400,
                }}
              >
                {p.name} <span style={muted}>{p.relationship.join('; ')}</span>
                <span data-testid="person-row-docs" style={{ ...muted, display: 'block' }}>
                  {p.document_count === 0
                    ? 'No documents open to the AI'
                    : `${p.document_count} ${p.document_count === 1 ? 'document' : 'documents'}${
                      dateRange(p.first_date, p.last_date) ? `, ${dateRange(p.first_date, p.last_date)}` : ''}`}
                </span>
              </button>
            </li>
          ))}
          {people && people.length === 0 && <li style={muted}>No people in the catalog.</li>}
        </ul>

        {personName && !person && !error && (
          <div role="status" style={{ ...muted, color: 'var(--text-secondary)' }}>Loading the record of {personName}…</div>
        )}

        {person && (
          <article aria-label={`Record: ${person.name}`}>
            <h2 style={{ margin: '0 0 4px', fontSize: 'var(--text-lg)', color: 'var(--text-primary)' }}>{person.name}</h2>
            {person.relationship.map((r) => (
              <div key={r} style={{ fontSize: 'var(--text-sm)', color: 'var(--text-secondary)' }}>{r}</div>
            ))}
            {range && <div data-testid="person-dates" style={{ fontSize: 'var(--text-sm)', color: 'var(--text-secondary)' }}>Documents dated {range}</div>}
            {person.titles.length > 0 && (
              <ul aria-label="Titles" style={{ listStyle: 'none', margin: '8px 0 20px', padding: 0 }}>
                {person.titles.map((t) => (
                  <li key={t.isbn ?? t.title} style={{ fontSize: 'var(--text-sm)', color: 'var(--text-primary)' }}>
                    {t.title} <span style={muted}>{t.role}{t.pub_date ? `, ${t.pub_date.slice(0, 4)}` : ''}</span>
                  </li>
                ))}
              </ul>
            )}
            {kindCounts.length > 0 && (
              <p data-testid="person-kinds" style={{ margin: '0 0 12px', fontSize: 'var(--text-sm)', color: 'var(--text-secondary)' }}>
                {kindCounts.map((k) => `${k.count} ${k.kind}`).join(', ')}
              </p>
            )}
            {items.length > 0 ? (
              <>
              <h3 style={{ margin: '0 0 8px', fontSize: 'var(--text-sm)', fontWeight: 600, color: 'var(--text-primary)' }}>Titles and documents</h3>
              <Timeline
                label={`Documents connected to ${person.name}, by title and year`}
                rows={person.rows}
                items={items}
                selected={personSelected}
                onSelect={(n) => set({ personSelected: n })}
                registerDot={(k, el) => { if (el) dotRefs.current.set(k, el); else dotRefs.current.delete(k) }}
              />
              </>
            ) : (
              <p style={{ fontSize: 'var(--text-sm)', color: 'var(--text-primary)' }}>No document open to the AI connects to {person.name}.</p>
            )}
            <div style={{ marginTop: 24, maxWidth: 720 }}>
              <NotOpen count={person.not_open.count} lines={person.not_open.reasons.map((r) => r.line)} />
            </div>
          </article>
        )}
      </div>

      {selected && (
        <PassagePanel
          passage={{ ...selected, how: selected.connections.join(' and '), matched: nameTerms(person?.name ?? '') }}
          onClose={() => set({ personSelected: null })}
        />
      )}
    </div>
  )
}
