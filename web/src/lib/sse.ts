/**
 * Shared SSE-stream parsing utility.
 *
 * Replaces ~30 lines of identical line-buffering + `data: {...}` parsing
 * previously duplicated across useSSEStream, Catalog/runFeature.ts, and
 * MaintainPanel's runFeature. Each consumer can now subscribe at the
 * granularity they care about (parsed event objects vs `[DONE]` sentinel).
 *
 * Usage:
 *
 *   for await (const evt of parseSSEStream(res, signal)) {
 *     if (evt.type === 'done') break
 *     if (evt.event === 'progress') ...
 *   }
 *
 * Aborts cleanly when `signal` is aborted by the caller. Yields a final
 * `{ type: 'done' }` sentinel when the server emits `data: [DONE]`.
 */

export type SSEParsedEvent =
  | { type: 'done' }
  | ({ type: 'event' } & Record<string, unknown>)

export async function* parseSSEStream(
  res: Response,
  signal?: AbortSignal,
): AsyncGenerator<SSEParsedEvent> {
  if (!res.body) throw new Error('No SSE body')
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''

  try {
    while (true) {
      if (signal?.aborted) return
      const { done, value } = await reader.read()
      // Flush the decoder on the final read so trailing multibyte bytes emit.
      buf += done ? decoder.decode() : decoder.decode(value, { stream: true })
      const lines = buf.split('\n')
      // On the final read, treat the remaining segment as a complete line —
      // otherwise a last frame with no trailing newline would be dropped.
      buf = done ? '' : (lines.pop() ?? '')
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue
        const payload = line.slice(6).trim()
        if (payload === '[DONE]') {
          yield { type: 'done' }
          continue
        }
        try {
          const evt = JSON.parse(payload) as Record<string, unknown>
          yield { type: 'event', ...evt }
        } catch {
          // keepalive / non-JSON data line — ignore
        }
      }
      if (done) return
    }
  } finally {
    // reader.cancel() returns a Promise that rejects with
    // `AbortError: BodyStreamBuffer was aborted` when the underlying stream
    // was already aborted (e.g., the consumer pressed Stop). The sync
    // try/catch can't catch a Promise rejection — attach a noop handler so
    // the rejection isn't reported as "Uncaught (in promise)".
    reader.cancel().catch(() => { /* already aborted/cancelled */ })
  }
}
