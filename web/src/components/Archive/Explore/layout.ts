/**
 * Timeline layout for Explore and People: pure functions, no DOM.
 *
 * One shared year scale for every row, so a gap between two years is the same
 * width in every row and years with no documents stay blank (nothing is
 * compressed). A dot sits at its date; dots that would overlap in a row move
 * to another lane of that row rather than shrinking.
 */

export interface TimelineRowIn {
  title?: string | null
  isbn?: string | null
  label: string
  passages: number[]
}

export interface DotIn {
  n: number
  date?: string | null
  year?: number | null
}

export interface YearScale {
  /** First year on the axis (the earliest document's year). */
  start: number
  /** Years the axis spans, counting the last document's year whole. */
  span: number
}

export interface PlacedDot {
  n: number
  /** 0..1 along the axis. */
  x: number
  lane: number
}

export interface PlacedRow {
  key: string
  label: string
  isPress: boolean
  dots: PlacedDot[]
  lanes: number
}

export interface Layout {
  scale: YearScale | null
  rows: PlacedRow[]
  /** Documents with no date at all: listed, not placed. */
  undated: number[]
}

export interface Tick { year: number; x: number }

const MONTH_NAMES = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
]

/** The year a dot belongs to: its `year`, else the year written in its date. */
export function yearOf(d: DotIn): number | null {
  if (typeof d.year === 'number') return d.year
  const m = d.date ? /^(\d{4})/.exec(d.date) : null
  return m ? Number(m[1]) : null
}

/** Fraction of its year that has passed on `date` (0 for a bare year). */
export function yearFraction(date: string | null | undefined): number {
  const m = date ? /^(\d{4})-(\d{2})-(\d{2})/.exec(date) : null
  if (!m) return 0
  const y = Number(m[1])
  const t = Date.UTC(y, Number(m[2]) - 1, Number(m[3]))
  const t0 = Date.UTC(y, 0, 1)
  const t1 = Date.UTC(y + 1, 0, 1)
  return Math.min(1, Math.max(0, (t - t0) / (t1 - t0)))
}

/** The axis runs from the earliest year to the end of the latest one. */
export function yearScale(dots: DotIn[]): YearScale | null {
  const years = dots.map(yearOf).filter((y): y is number => y !== null)
  if (years.length === 0) return null
  const start = Math.min(...years)
  return { start, span: Math.max(...years) - start + 1 }
}

/** Where a dot sits on the axis, 0..1. Null when it has no year. */
export function dotX(scale: YearScale, d: DotIn): number | null {
  const y = yearOf(d)
  if (y === null) return null
  return (y - scale.start + yearFraction(d.date)) / scale.span
}

/**
 * Lanes inside one row: dots sorted by x, each placed in the first lane whose
 * last dot is at least `minGapPx` away on an axis `widthPx` wide.
 */
export function assignLanes(xs: { n: number; x: number }[], widthPx: number, minGapPx: number): PlacedDot[] {
  const sorted = [...xs].sort((a, b) => a.x - b.x || a.n - b.n)
  const lastX: number[] = []
  return sorted.map(({ n, x }) => {
    let lane = lastX.findIndex((lx) => (x - lx) * widthPx >= minGapPx)
    if (lane < 0) lane = lastX.length
    lastX[lane] = x
    return { n, x, lane }
  })
}

/** Rows as placed dots. Row order is the response's: titles, then Press. */
export function layoutRows(
  rows: TimelineRowIn[],
  dots: DotIn[],
  widthPx: number,
  minGapPx = 28,
): Layout {
  const byN = new Map(dots.map((d) => [d.n, d]))
  const scale = yearScale(dots)
  const placedRows: PlacedRow[] = rows.map((r) => {
    const xs: { n: number; x: number }[] = []
    for (const n of r.passages) {
      const d = byN.get(n)
      const x = d && scale ? dotX(scale, d) : null
      if (x !== null) xs.push({ n, x })
    }
    const placed = scale ? assignLanes(xs, widthPx, minGapPx) : []
    return {
      key: r.isbn ?? r.title ?? r.label,
      label: r.label,
      isPress: !r.title,
      dots: placed,
      lanes: Math.max(1, ...placed.map((p) => p.lane + 1)),
    }
  })
  const undated = dots.filter((d) => yearOf(d) === null).map((d) => d.n)
  return { scale, rows: placedRows, undated }
}

/**
 * Year labels for the axis: every year from the first to the last, empty ones
 * included, so the even spacing reads as years. When a label per year would
 * sit closer than `minGapPx`, every k-th year is labelled instead, counted
 * from the first.
 */
export function axisTicks(scale: YearScale, _dots: DotIn[], widthPx: number, minGapPx = 44): Tick[] {
  const perYear = widthPx / scale.span
  const step = Math.max(1, Math.ceil(minGapPx / Math.max(perYear, 1e-6)))
  const out: Tick[] = []
  for (let i = 0; i < scale.span; i += step) out.push({ year: scale.start + i, x: i / scale.span })
  return out
}

/** "12 March 2019", "2019" for a bare year, "" for nothing. */
export function formatDate(date: string | null | undefined, year?: number | null): string {
  const m = date ? /^(\d{4})-(\d{2})-(\d{2})/.exec(date) : null
  if (m) return `${Number(m[3])} ${MONTH_NAMES[Number(m[2]) - 1]} ${m[1]}`
  if (date && /^\d{4}$/.test(date)) return date
  return typeof year === 'number' ? String(year) : ''
}

/** "12 March 2012 to 4 June 2026", or the one date when they are the same. */
export function dateRange(first: string | null | undefined, last: string | null | undefined): string {
  if (!first) return ''
  return last && last !== first ? `${formatDate(first)} to ${formatDate(last)}` : formatDate(first)
}

/** How an Explore passage matched, in words. */
export function howMatched(how: 'phrase' | 'terms', matched: string[]): string {
  const words = matched.join(', ')
  if (how === 'phrase') return words ? `matched the phrase ${words}` : 'matched the phrase'
  return words ? `matched the words ${words}` : 'matched the words'
}
