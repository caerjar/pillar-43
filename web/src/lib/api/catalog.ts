/**
 * Catalog operations API client.
 *
 * Covers: status/stats, indexing runs, transcription, passes (dedup/tasks/dispatch/etc),
 * empties, code projects, inbox management.
 */

import type { CatalogStatus, CatalogStats, InboxItem } from './_types'
import { BASE, req } from './_fetch'

export const catalogApi = {
  // ── Status & Stats ───────────────────────────────────────────────────────

  catalogStatus: () =>
    req<CatalogStatus & {
      // Legacy local-only fields (not in Pydantic model). Keep for compat
      // with code that hasn't migrated yet.
      thread_count: number
      last_scan: number | null
      interrupted: boolean
      error?: string
    }>('/api/catalog/status'),

  catalogStats: () =>
    req<CatalogStats>('/api/catalog/stats'),

  catalogBreakdown: () =>
    req<{
      total: number
      summarized: number
      extracted: number
      last_indexed: string | number | null
      interrupted: boolean
      by_mount: Array<{
        mount: string
        total: number
        summarized: number
        extracted: number
      }>
    }>('/api/catalog/breakdown'),

  catalogEstimate: () =>
    req<{
      total_files: number
      files_needing_summary: number
      files_needing_embedding: number
      phases: Array<{
        id: string
        label: string
        description: string
        estimated_files: number
        estimated_seconds: number
      }>
      total_estimated_seconds: number
    }>('/api/catalog/estimate'),

  catalogIndexStatus: () =>
    req<{
      total_filesystem_files: number
      indexed_files: number
      pending_files: number
      needs_summary: number
      needs_embedding: number
      last_run_timestamp: number | null
      interrupted: boolean
    }>('/api/catalog/index-status'),

  // ── Catalog Run (SSE) ────────────────────────────────────────────────────

  catalogRun: (forceRescan = false, mounts?: string[], signal?: AbortSignal) =>
    fetch(BASE + '/api/catalog/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ force_rescan: forceRescan, ...(mounts ? { mounts } : {}) }),
      signal,
    }),

  // W4-A: per-file re-extract + re-summarize. Skips connections, threads,
  // ghosts, etc. — those stay vault-wide via their own buttons.
  catalogRunForFile: (path: string, signal?: AbortSignal) =>
    fetch(BASE + '/api/catalog/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path }),
      signal,
    }),

  reindexBackground: (forceRescan = false, mounts?: string[]) =>
    req<{ job_id: string; status: string }>('/api/catalog/reindex', {
      method: 'POST',
      body: JSON.stringify({ force_rescan: forceRescan, mounts }),
    }),

  // Hard-stop: marks any running 'Indexing vault' / 'Reindex vault' job as
  // failed in the DB. Used as a fallback when soft cancel doesn't take —
  // typically because the background thread is wedged in a C extension and
  // can't poll cancel_requested.
  catalogForceStop: () =>
    req<{ cleared: string[] }>('/api/catalog/force-stop', { method: 'POST' }),

  // ── Transcription ────────────────────────────────────────────────────────

  // SSE stream of progress events while transcribing one multimedia file.
  // Pass `force: true` to bypass the source-hash skip and regenerate.
  transcribe: (path: string, opts: { force?: boolean; signal?: AbortSignal } = {}) =>
    fetch(BASE + '/api/transcribe', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path, force: opts.force ?? false }),
      signal: opts.signal,
    }),

  // SSE stream of progress while transcribing a handwritten note
  // (image, .heic, or multi-page PDF) into markdown + optional SVG diagrams.
  // Distinct from /api/transcribe — different file-type set + multi-artifact
  // response. Done event carries { transcript_path, diagram_paths,
  // diagrams_found, pages_processed }.
  transcribeHandwriting: (path: string, opts: { force?: boolean; signal?: AbortSignal } = {}) =>
    fetch(BASE + '/api/handwriting/transcribe', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path, force: opts.force ?? false }),
      signal: opts.signal,
    }),

  transcribeEstimate: (paths: string[]) =>
    req<{
      total_duration_seconds: number
      estimated_processing_seconds: number
      items: { path: string; duration_seconds: number; estimated_processing_seconds: number }[]
    }>('/api/transcribe/estimate', {
      method: 'POST',
      body: JSON.stringify({ paths }),
    }),

  // ── Catalog Passes (SSE endpoints) ───────────────────────────────────────
  //
  // All accept an optional AbortSignal so the Maintain panel's per-feature
  // Stop button can abort the SSE stream. Pre-PR-7 only catalogRun had this.

  catalogDedup: (signal?: AbortSignal) =>
    fetch(BASE + '/api/catalog/dedup', { method: 'POST', signal }),

  catalogTasks: (signal?: AbortSignal) =>
    fetch(BASE + '/api/catalog/tasks', { method: 'POST', signal }),

  catalogDispatch: (signal?: AbortSignal) =>
    fetch(BASE + '/api/catalog/dispatch', { method: 'POST', signal }),

  catalogConnections: (signal?: AbortSignal) =>
    fetch(BASE + '/api/catalog/connections', { method: 'POST', signal }),

  catalogInbox: (signal?: AbortSignal) =>
    fetch(BASE + '/api/catalog/inbox', { method: 'POST', signal }),

  catalogLoadBearing: (signal?: AbortSignal) =>
    fetch(BASE + '/api/catalog/load-bearing', { method: 'POST', signal }),

  catalogPeriodicReview: (signal?: AbortSignal) =>
    fetch(BASE + '/api/catalog/periodic-review', { method: 'POST', signal }),

  catalogReextract: (signal?: AbortSignal) =>
    fetch(BASE + '/api/catalog/reextract', { method: 'POST', signal }),

  // ── Empties ──────────────────────────────────────────────────────────────

  emptiesFiles: (threshold = 300) =>
    req<{
      items: { rel_path: string; mount: string; size_bytes: number; char_count: number; summary: string | null; writable: boolean }[]
      threshold: number
    }>(`/api/catalog/empties?threshold=${threshold}`),

  // ── Inbox ────────────────────────────────────────────────────────────────

  inboxPending: () =>
    req<{ items: InboxItem[]; error?: string }>('/api/catalog/inbox/pending'),

  inboxMove: (source: string, dest: string) =>
    req<{ ok: boolean; source: string; dest: string }>('/api/catalog/inbox/move', {
      method: 'POST',
      body: JSON.stringify({ source, dest }),
    }),

  inboxDelete: (path: string) =>
    req<{ ok: boolean; error?: string }>('/api/catalog/inbox/delete', {
      method: 'POST',
      body: JSON.stringify({ path }),
    }),
}
