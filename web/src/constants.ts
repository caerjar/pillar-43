/**
 * Frontend constants — single source of truth for magic numbers.
 *
 * Anything used in more than one component or any non-obvious literal
 * (durations, sizes, thresholds) belongs here.
 */

// ── React Query staleTimes ──────────────────────────────────────────────────

/** Per-query staleTime, named by CADENCE rather than by consumer.
 *
 * Consumer-named buckets (the previous FILE / CATALOG_STATS / SETTINGS) do not
 * survive contact with reuse: 60s was in use at 13 call sites, only some of
 * them catalog stats, so the name stopped describing the value. Naming by how
 * fast the data actually moves means a new query picks a bucket by asking one
 * answerable question.
 *
 * These are the values already in use across the app, kept identical — this
 * block previously declared itself "single source of truth" while being
 * referenced by exactly zero call sites.
 */
export const STALE_TIME = {
  /** 1s — changes constantly while running. Jobs. */
  LIVE: 1_000,
  /** 5s — near-live: queues, pending/consent state. */
  FREQUENT: 5_000,
  /** 10s — the active working set. */
  ACTIVE: 10_000,
  /** 30s — the default. Tree, threads, most lists. */
  DEFAULT: 30_000,
  /** 60s — slow-moving aggregates. Catalog stats, graph, skills. */
  SLOW: 60_000,
  /** 5min — only changes via our own writes. File content, settings. */
  STATIC: 5 * 60_000,
} as const

// ── UI durations & sizes ────────────────────────────────────────────────────

/** ms — debounce for live search inputs. */
export const SEARCH_DEBOUNCE_MS = 250

/** ms — debounce for editor autosave. */
export const AUTOSAVE_DEBOUNCE_MS = 1_000

/** ms — toast auto-dismiss. */
export const TOAST_DURATION_MS = 5_000

/** ms — animation transitions (modals, panels). */
export const TRANSITION_MS = 200

/** Default left panel width in px. */
export const LEFT_PANEL_WIDTH_DEFAULT = 280
export const LEFT_PANEL_WIDTH_MIN = 220
export const LEFT_PANEL_WIDTH_MAX = 900

/** Default AI sidebar width in px. */
export const AI_SIDEBAR_WIDTH_DEFAULT = 340
export const AI_SIDEBAR_WIDTH_MIN = 280
export const AI_SIDEBAR_WIDTH_MAX = 800

/** Max height for inline log viewers (catalog feature rows etc.). */
export const LOG_VIEWER_MAX_HEIGHT = 180

/** Cap on log entries kept in memory per feature run. */
export const LOG_ENTRY_CAP = 200

// ── Catalog / job thresholds ────────────────────────────────────────────────

/** ms between SSE event polls when the queue is empty. */
export const SSE_POLL_TIMEOUT_MS = 150

// ── List virtualization (used by Day 11 perf work) ───────────────────────────

/** Item count above which a list should virtualize. */
export const VIRTUALIZE_THRESHOLD = 100
