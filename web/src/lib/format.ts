/**
 * Human-readable formatting helpers — shared across panels.
 *
 * Originally duplicated inside CatalogPanel.tsx and MaintainPanel.tsx.
 * Centralised here so behaviour stays consistent and any future tweak
 * (e.g. localised time, "1d ago" vs "yesterday") happens in one place.
 */

/**
 * "Apr 27, 2026 14:30" or "never" if no timestamp.
 *
 * Accepts number (epoch seconds) or string (ISO-8601). The Pydantic models
 * type these as `float | str | None` because the on-disk format mixes both;
 * we coerce here so callers don't have to.
 */
export function formatTime(t: number | string | null | undefined): string {
  if (t === null || t === undefined || t === '') return 'never'
  const d =
    typeof t === 'number' ? new Date(t < 1e12 ? t * 1000 : t) : new Date(t)
  if (isNaN(d.getTime())) return 'never'
  return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

/** "just now" / "3 minutes ago" / "2 days ago" / "5 months ago" / "1 year ago". */
export function formatRelativeTime(t: number | string): string {
  // Coerce ISO-8601 strings to epoch seconds; numbers <1e12 are already seconds.
  const epoch =
    typeof t === 'string' ? new Date(t).getTime() / 1000 : t < 1e12 ? t : t / 1000
  const nowSec = Date.now() / 1000
  const diffSec = nowSec - epoch
  if (diffSec < 60) return 'just now'
  if (diffSec < 3600) {
    const mins = Math.floor(diffSec / 60)
    return `${mins} minute${mins !== 1 ? 's' : ''} ago`
  }
  if (diffSec < 86400) {
    const hrs = Math.floor(diffSec / 3600)
    return `${hrs} hour${hrs !== 1 ? 's' : ''} ago`
  }
  const days = Math.floor(diffSec / 86400)
  if (days < 30) return `${days} day${days !== 1 ? 's' : ''} ago`
  const months = Math.floor(days / 30)
  if (months < 12) return `${months} month${months !== 1 ? 's' : ''} ago`
  const years = Math.floor(months / 12)
  return `${years} year${years !== 1 ? 's' : ''} ago`
}

/** "2.4 KB" / "1.2 MB" / "3.4 GB". */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  return `${(bytes / 1024 / 1024 / 1024).toFixed(1)} GB`
}

/** Short file-type label derived from extension: PDF / Audio / Video / EPUB / Note / File. */
export function getFileBadge(filename: string): string {
  const ext = filename.split('.').pop()?.toLowerCase() ?? ''
  if (ext === 'pdf') return 'PDF'
  if (['mp3', 'm4a', 'wav'].includes(ext)) return 'Audio'
  if (['mp4', 'mov'].includes(ext)) return 'Video'
  if (ext === 'epub') return 'EPUB'
  if (ext === 'md') return 'Note'
  return 'File'
}
