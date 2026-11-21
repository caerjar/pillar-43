import type { api } from '../../lib/api'

/** The shape `GET /api/settings` returns. Codegen-derived; never hand-typed. */
export type AppSettings = Awaited<ReturnType<typeof api.appSettings>>

/**
 * The canonical settings write path, threaded to every section as a prop.
 *
 * Implemented once in `SettingsWindow.tsx` (optimistic → api.updateSettings →
 * qc.setQueryData(['app-settings'])). Sections must not duplicate it or hold
 * their own per-row save state — see the maintainer notes § "Settings flow".
 */
export type UpdateFn = (u: Parameters<typeof api.updateSettings>[0]) => void
