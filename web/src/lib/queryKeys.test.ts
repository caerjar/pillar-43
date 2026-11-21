/**
 * Guard on cache cadence.
 *
 * React Query refetches by staleTime. The ladder below is pinned so a rename or
 * retune is a deliberate edit to this test, not a silent change to how often
 * every query in the app refetches.
 */
import { describe, it, expect } from 'vitest'
import { STALE_TIME } from '../constants'

describe('STALE_TIME', () => {
  it('pins the cadence ladder', () => {
    // Pinned so a rename or retune is a deliberate edit to this test, not a
    // silent change to how often every query in the app refetches.
    expect(STALE_TIME).toEqual({
      LIVE: 1_000,
      FREQUENT: 5_000,
      ACTIVE: 10_000,
      DEFAULT: 30_000,
      SLOW: 60_000,
      STATIC: 5 * 60_000,
    })
  })

  it('is strictly ascending, so the names order by cadence', () => {
    const values = Object.values(STALE_TIME)
    const sorted = [...values].sort((a, b) => a - b)
    expect(values).toEqual(sorted)
  })
})
