/**
 * Press archive API client.
 *
 * The types below are written by hand and mirror `api/routes/archive.py`.
 * They stay hand-written until `./scripts/codegen-types` runs over the
 * archive routes; replace them with `_generated.ts` types then.
 */

import { BASE, req } from './_fetch'
import type { components } from './_generated'

/** GET /api/archive/profile. */
export interface ArchiveProfile {
  title?: string
  org_name?: string
  nav?: string[]
  answer_model?: string
}

export interface AskQuote {
  /** Passage number (the `n` of an entry in `passages`). */
  passage: number
  /** 1-based: the quoted sentence is `sentences[sentence - 1]`. */
  sentence: number
  /** The quoted words, taken from the source text by the backend. */
  text: string
}

export interface AskAnswerSentence {
  text: string
  /** Passage numbers (`passages[].n`). */
  cites: number[]
  quote: AskQuote | null
}

export interface AskPassage {
  n: number
  path: string
  title: string
  kind: string
  chunk_id: string | number
  ordinal: number
  heading: string | null
  /** PDF page the passage starts on; null for texts without pages. */
  page?: number | null
  /** The work the item is about, read from its text (not the file name). */
  work_title?: string | null
  isbn?: string | null
  sentences: string[]
}

export interface AskStaffOnlySource {
  path: string
  title: string
  kind: string
}

/** What the archive could not say, computed by the backend. `line` is the
 *  sentence to show; it is empty when there is nothing to report. */
export interface AskSilences {
  closed: number
  missing_correspondents: string[]
  empty_years: number[]
  /** Closed items by who closed them: their writers, the intake default, or staff. */
  closed_by?: { writer: number; default: number; staff: number }
  /** Items the question names that are closed or withdrawn; `reason` says who in plain words. */
  closed_named?: { path: string; title: string; kind: string | null; state?: string; reason?: string }[]
  /** The question names a title and a kind of document the archive does not hold. */
  no_document?: { title: string; kind: string } | null
  line: string
}

export interface AskResponse {
  question: string
  answer: AskAnswerSentence[]
  not_answered: boolean
  would_answer: string | null
  passages: AskPassage[]
  staff_only_sources: AskStaffOnlySource[]
  withheld_from_ai: number
  silences?: AskSilences
  model: string
  timing: { retrieve_s: number; model_s: number }
}

export type OpenToAi = components['schemas']['OpenToAi']
export type PassageBoxes = components['schemas']['PassageBoxes']

/** What the AI may read for a question, by kind (GET /api/archive/open-to-ai). */
export async function fetchOpenToAi(signal?: AbortSignal): Promise<OpenToAi> {
  return req<OpenToAi>('/api/archive/open-to-ai', { signal })
}

/** Where cited text sits on a PDF page, as fractions of the page. */
export async function fetchPassageBoxes(
  path: string, page: number, text: string, signal?: AbortSignal,
): Promise<PassageBoxes> {
  const q = new URLSearchParams({ path, page: String(page), text })
  return req<PassageBoxes>(`/api/archive/passage-boxes?${q}`, { signal })
}

/** Thrown for a 503: the local model is not running. */
export class ModelUnavailableError extends Error {
  constructor() {
    super('The local model is not running.')
    this.name = 'ModelUnavailableError'
  }
}

const PROFILE_TIMEOUT_MS = 4_000

/**
 * Never throws: any failure (network, non-2xx, bad JSON) answers an empty
 * profile, so the shell falls back to the default title. A failed fetch must
 * never route into the first-run wizard (the maintainer notes pitfall).
 */
export async function fetchArchiveProfile(): Promise<ArchiveProfile> {
  const ctl = new AbortController()
  const timer = setTimeout(() => ctl.abort(), PROFILE_TIMEOUT_MS)
  try {
    const res = await fetch(BASE + '/api/archive/profile', { signal: ctl.signal })
    if (!res.ok) return {}
    return ((await res.json()) as ArchiveProfile) ?? {}
  } catch {
    return {}
  } finally {
    clearTimeout(timer)
  }
}

export async function askArchive(question: string, signal?: AbortSignal): Promise<AskResponse> {
  try {
    return await req<AskResponse>('/api/archive/ask', {
      method: 'POST',
      body: JSON.stringify({ question }),
      signal,
    })
  } catch (e) {
    if (e instanceof Error && /^503\b/.test(e.message)) throw new ModelUnavailableError()
    throw e
  }
}

// ── Sessions ────────────────────────────────────────────────────────────────

/** `open`: no accounts exist yet. `signed-out`: accounts exist and this
 *  browser has no valid session (GET /me answered 401). `unreachable`: the
 *  answer is unknown (network, 5xx); never treated as any of the others. */
export type Session =
  | { state: 'open' }
  | { state: 'signed-in'; name: string; role: string }
  | { state: 'signed-out' }
  | { state: 'unreachable' }

export async function fetchSession(): Promise<Session> {
  try {
    const res = await fetch(BASE + '/api/archive/me')
    if (res.status === 401) return { state: 'signed-out' }
    if (!res.ok) return { state: 'unreachable' }
    const body = (await res.json()) as { name: string | null; role: string | null }
    return body.name ? { state: 'signed-in', name: body.name, role: body.role ?? '' } : { state: 'open' }
  } catch {
    return { state: 'unreachable' }
  }
}

/** Resolves with the account on success; rejects with a plain-words message. */
export async function signIn(name: string, password: string): Promise<{ name: string; role: string }> {
  let res: Response
  try {
    res = await fetch(BASE + '/api/archive/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, password }),
    })
  } catch {
    throw new Error('Cannot reach the archive. Check the connection and try again.')
  }
  if (res.status === 401) throw new Error('Wrong name or password.')
  if (!res.ok) throw new Error('Sign-in failed. Try again in a moment.')
  return (await res.json()) as { name: string; role: string }
}

export async function signOut(): Promise<void> {
  await fetch(BASE + '/api/archive/logout', { method: 'POST' })
}

// ── Explore and People (whole-archive views) ───────────────────────────────

export type ExploreResponse = components['schemas']['ExploreResponse']
export type ExplorePassage = components['schemas']['ExplorePassage']
export type PersonRecord = components['schemas']['PersonRecord']
export type PersonItem = components['schemas']['PersonItem']
export type PersonSummary = components['schemas']['PersonSummary']

/** POST /api/archive/explore: every passage open to the AI on a topic, a dated
 *  summary whose lines cite them, and the count of matching items not open to
 *  it. `summarize: false` skips the model call. */
export async function exploreArchive(
  query: string,
  opts: { summarize?: boolean; signal?: AbortSignal } = {},
): Promise<ExploreResponse> {
  return req<ExploreResponse>('/api/archive/explore', {
    method: 'POST',
    body: JSON.stringify({ query, summarize: opts.summarize ?? true }),
    signal: opts.signal,
  })
}

// ── The writer's terms view ─────────────────────────────────────────────────

export type MyWorkResponse = components['schemas']['MyWorkResponse']
export type MyWorkItem = components['schemas']['MyWorkItem']
export type LabelNotice = components['schemas']['LabelNotice']

export type ConsentLevel = 'private' | 'staff' | 'model'

/** GET /api/archive/my-work: the signed-in writer's own items only, with the
 *  access log from the ledger (never the question text). 403 for anyone else. */
export async function fetchMyWork(signal?: AbortSignal): Promise<MyWorkResponse> {
  return req<MyWorkResponse>('/api/archive/my-work', { signal })
}

export async function setItemConsent(path: string, level: ConsentLevel): Promise<void> {
  await req('/api/archive/items/consent', { method: 'POST', body: JSON.stringify({ path, level }) })
}

export async function setItemLabels(path: string, labels: string[]): Promise<void> {
  await req('/api/archive/items/labels', { method: 'POST', body: JSON.stringify({ path, labels }) })
}

export async function withdrawItem(path: string): Promise<void> {
  await req('/api/archive/withdraw', { method: 'POST', body: JSON.stringify({ path }) })
}

/** GET /api/archive/people: the people the catalog credits. */
export async function fetchPeople(signal?: AbortSignal): Promise<PersonSummary[]> {
  return req<PersonSummary[]>('/api/archive/people', { signal })
}

/** GET /api/archive/people/{name}: one person's connected items, each marked
 *  signed, wrote, received or mentioned. Rejects with a 404 message when the
 *  archive has nothing on the name. */
export async function fetchPersonRecord(name: string, signal?: AbortSignal): Promise<PersonRecord> {
  return req<PersonRecord>('/api/archive/people/' + encodeURIComponent(name), { signal })
}
