import { describe, expect, it } from 'vitest'
import { assignLanes, axisTicks, dotX, formatDate, howMatched, layoutRows, yearFraction, yearScale } from './layout'

const dots = [
  { n: 1, date: '2019-03-12', year: 2019 },
  { n: 2, date: '2021-06-08', year: 2021 },
  { n: 3, date: '2026-08-24', year: 2026 },
]

describe('yearScale', () => {
  it('runs from the earliest year to the end of the latest', () => {
    expect(yearScale(dots)).toEqual({ start: 2019, span: 8 })
  })
  it('is null with no dated documents', () => {
    expect(yearScale([{ n: 1 }])).toBeNull()
  })
  it('one year spans one year', () => {
    expect(yearScale([{ n: 1, year: 2022 }])).toEqual({ start: 2022, span: 1 })
  })
})

describe('dotX', () => {
  it('puts a dot at its date, with empty years taking their full width', () => {
    const s = yearScale(dots)!
    expect(dotX(s, dots[0])).toBeCloseTo(yearFraction('2019-03-12') / 8, 6)
    // 2020 has no document and still occupies 1/8 of the axis.
    expect(dotX(s, { n: 9, date: '2021-01-01' })).toBeCloseTo(2 / 8, 6)
    expect(dotX(s, { n: 9, date: '2019-01-01' })).toBe(0)
  })
  it('falls back to the year written in the date', () => {
    const s = yearScale(dots)!
    expect(dotX(s, { n: 9, date: '2020-01-01' })).toBeCloseTo(1 / 8, 6)
  })
  it('is null for a dot with no year', () => {
    expect(dotX({ start: 2019, span: 2 }, { n: 1 })).toBeNull()
  })
})

describe('assignLanes', () => {
  it('keeps distant dots in lane 0', () => {
    expect(assignLanes([{ n: 1, x: 0.1 }, { n: 2, x: 0.5 }], 1000, 28).map((d) => d.lane)).toEqual([0, 0])
  })
  it('moves a crowding dot to the next lane and reuses lane 0 once clear', () => {
    const out = assignLanes([{ n: 1, x: 0.1 }, { n: 2, x: 0.11 }, { n: 3, x: 0.2 }], 1000, 28)
    expect(out.map((d) => [d.n, d.lane])).toEqual([[1, 0], [2, 1], [3, 0]])
  })
  it('is independent of input order', () => {
    const a = assignLanes([{ n: 2, x: 0.11 }, { n: 1, x: 0.1 }], 1000, 28)
    expect(a.map((d) => d.n)).toEqual([1, 2])
  })
})

describe('layoutRows', () => {
  const rows = [
    { title: 'Ninety Tides', isbn: '1', label: 'Ninety Tides', passages: [2, 3] },
    { title: null, isbn: null, label: 'Press', passages: [1] },
    { title: 'Empty', isbn: '2', label: 'Empty', passages: [] },
  ]
  it('keeps the response order, marks Press and shares one scale', () => {
    const l = layoutRows(rows, dots, 800)
    expect(l.rows.map((r) => [r.label, r.isPress, r.dots.length])).toEqual([
      ['Ninety Tides', false, 2], ['Press', true, 1], ['Empty', false, 0],
    ])
    expect(l.scale).toEqual({ start: 2019, span: 8 })
    expect(l.rows[2].lanes).toBe(1)
  })
  it('lists undated documents instead of placing them', () => {
    const l = layoutRows([{ title: 'T', label: 'T', passages: [7] }], [{ n: 7 }, { n: 8, year: 2020 }], 800)
    expect(l.undated).toEqual([7])
    expect(l.rows[0].dots).toEqual([])
  })
  it('a dot cited by two titles appears in both rows', () => {
    const l = layoutRows(
      [{ title: 'A', label: 'A', passages: [1] }, { title: 'B', label: 'B', passages: [1] }],
      dots, 800,
    )
    expect(l.rows.map((r) => r.dots.map((d) => d.n))).toEqual([[1], [1]])
  })
})

describe('axisTicks', () => {
  it('labels every year in the span, empty years included, evenly spaced', () => {
    const s = yearScale(dots)!
    const t = axisTicks(s, dots, 2000)
    expect(t.map((x) => x.year)).toEqual([2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026])
    const gaps = t.slice(1).map((x, i) => x.x - t[i].x)
    gaps.forEach((g) => expect(g).toBeCloseTo(1 / 8, 9))
  })
  it('labels every k-th year when a label per year would crowd', () => {
    const s = yearScale(dots)!
    expect(axisTicks(s, dots, 100).map((t) => t.year)).toEqual([2019, 2023])
  })
})

describe('text', () => {
  it('formats dates', () => {
    expect(formatDate('2019-03-12')).toBe('12 March 2019')
    expect(formatDate(null, 2020)).toBe('2020')
    expect(formatDate(null)).toBe('')
  })
  it('says how a passage matched', () => {
    expect(howMatched('phrase', ['wharf yellow'])).toBe('matched the phrase wharf yellow')
    expect(howMatched('terms', ['magenta', 'yellow'])).toBe('matched the words magenta, yellow')
  })
})
