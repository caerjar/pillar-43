import { useEffect, useState } from 'react'

/**
 * Live viewport breakpoint state. Recomputes on window resize.
 *
 *   - `narrow` — viewport width < 1024px (iPad landscape and below).
 *     UI should reduce non-essential surfaces (AI sidebar collapses by default).
 *   - `tiny` — viewport width < 768px (iPad portrait and below).
 *     UI should hide non-essential surfaces entirely; phone widths are
 *     not a supported target — we just want the layout to not break.
 *
 * Server-safe: returns false/false during SSR / initial render before
 * `window` is available.
 */
export interface ViewportState {
  narrow: boolean
  tiny: boolean
}

function read(): ViewportState {
  if (typeof window === 'undefined') return { narrow: false, tiny: false }
  const w = window.innerWidth
  return { narrow: w < 1024, tiny: w < 768 }
}

export function useViewport(): ViewportState {
  const [state, setState] = useState<ViewportState>(read)
  useEffect(() => {
    const onResize = () => setState(read())
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])
  return state
}
