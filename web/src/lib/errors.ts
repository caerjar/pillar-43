/**
 * One way to get a message out of an unknown caught value.
 *
 * `catch (e)` binds `unknown`, and the codebase had three answers to that:
 * `(e as Error).message` (53 sites), `e instanceof Error ? … : …` (8), and
 * `String(e)` (4).
 *
 * The 53 are the problem, and not only stylistically. The cast is a lie the
 * compiler cannot check: if the thrown value is not an Error — a bare string,
 * a rejected non-Error, an object from a library — `.message` is `undefined`
 * and the user gets a toast that reads "undefined". That is strictly worse
 * than a generic message, because it looks like a bug in the app rather than
 * a failure that happened.
 */
import { ApiStructuredError } from './api/_fetch'

/**
 * Best available human-readable message for a caught value.
 *
 * Never returns an empty string: an empty toast is indistinguishable from a
 * broken one, so a caller-supplied fallback is used instead.
 */
export function errorMessage(e: unknown, fallback = 'Something went wrong'): string {
  if (e instanceof Error) return e.message || fallback
  if (typeof e === 'string') return e || fallback
  // Duck-typed: some libraries reject with a plain object carrying `message`.
  if (e && typeof e === 'object' && 'message' in e) {
    const m = (e as { message: unknown }).message
    if (typeof m === 'string' && m) return m
  }
  return fallback
}

/**
 * True when the API returned a structured error the UI dispatches on
 * (billing exhausted, auth failure, model not found).
 *
 * Prefer this over string-matching a message — those are user-facing prose
 * and get reworded.
 */
export function isStructuredError(e: unknown): e is ApiStructuredError {
  return e instanceof ApiStructuredError
}
