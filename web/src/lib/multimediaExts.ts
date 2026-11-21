// Single source of truth for multimedia extension sets on the frontend.
// Mirrors api/services/_media_exts.py. Drift between front and back is
// acceptable — multimedia formats are stable. If it ever matters, plumb
// the backend list through /api/settings.

export const IMAGE_EXTS = ['.jpg', '.jpeg', '.png', '.webp', '.gif'] as const

export const AUDIO_EXTS = [
  '.mp3', '.wav', '.ogg', '.m4a', '.flac',
  '.aac', '.m4b', '.opus', '.aif', '.aiff',
] as const

export const VIDEO_EXTS = ['.mp4', '.mov', '.mkv', '.webm'] as const

// .svg is NOT here — it's served as editable text and rendered via the
// editor's Edit/View toggle (View = rendered SVG, Edit = source), so it never
// hits the read-only binary image viewer.
export const IMAGE_VIEWER_EXTS = [...IMAGE_EXTS] as const

export const TRANSCRIBABLE_EXTS = [
  ...IMAGE_EXTS, ...AUDIO_EXTS, ...VIDEO_EXTS,
] as const

// Files the right-click "Transcribe handwriting" action accepts. Superset
// of IMAGE_EXTS plus .heic (iPhone scans; backend transcodes to JPEG
// before the vision call) and .pdf (multi-page; backend renders each
// page to PNG, sends it to the local vision model, assembles into one markdown).
// HEIC stays out of IMAGE_VIEWER_EXTS because browsers can't render it
// inline — we still want the menu action available, just not the preview.
export const HANDWRITING_EXTS = [
  ...IMAGE_EXTS, '.heic', '.pdf',
] as const
