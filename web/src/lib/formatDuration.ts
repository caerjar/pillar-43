/**
 * Format seconds into human-readable duration string.
 *
 * Examples:
 * - 30 → "30s"
 * - 90 → "1m 30s"
 * - 150 → "2m 30s"
 * - 3600 → "1h"
 * - 3690 → "1h 1m"
 */
export function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds}s`

  const mins = Math.floor(seconds / 60)
  const secs = seconds % 60

  if (mins < 60) {
    return secs > 0 ? `${mins}m ${secs}s` : `${mins}m`
  }

  const hours = Math.floor(mins / 60)
  const remainMins = mins % 60

  if (remainMins > 0) {
    return `${hours}h ${remainMins}m`
  }

  return `${hours}h`
}
