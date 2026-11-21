/**
 * Shared fetch utility for all API modules.
 *
 * All domain modules (files.ts, catalog.ts, etc.) import and use this.
 * Centralizes BASE URL handling and error responses.
 */

export const BASE = import.meta.env.VITE_API_URL ?? ''

/**
 * Error thrown when the backend returns a non-ok response with a structured
 * `detail: { error_code, message }` body (e.g. 401 authentication_error,
 * 402 billing_exhausted, 429 rate_limit_error). Carries the machine-readable
 * code so consumers can dispatch to `useStructuredErrorAlert` without
 * regex-matching the message. Parallel to SSEStructuredError in `lib/sse.ts`.
 */
export class ApiStructuredError extends Error {
  status: number
  code: string

  constructor(status: number, code: string, message: string) {
    super(message)
    this.name = 'ApiStructuredError'
    this.status = status
    this.code = code
    this.message = message
  }
}

export async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, {
    headers: { 'Content-Type': 'application/json', ...init?.headers },
    ...init,
  })
  if (!res.ok) {
    const body = await res.text()
    // Detect structured FastAPI HTTPException(detail={error_code, message}).
    // When present, surface as ApiStructuredError so the caller can route to
    // the toast layer without parsing the message string.
    try {
      const parsed = JSON.parse(body) as { detail?: { error_code?: string; message?: string } }
      const code = parsed?.detail?.error_code
      const msg = parsed?.detail?.message
      if (code) {
        throw new ApiStructuredError(res.status, code, msg ?? `${res.status} ${res.statusText}`)
      }
    } catch (e) {
      // Re-throw our own structured error; suppress JSON.parse failures only.
      if (e instanceof ApiStructuredError) throw e
    }
    throw new Error(`${res.status} ${res.statusText}: ${body}`)
  }
  // 204 No Content (e.g. DELETE /channels/{slug}) has an empty body; res.json()
  // would throw SyntaxError and a successful call would land in onError.
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}
