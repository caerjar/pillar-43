/**
 * FileTree type definitions and constants.
 *
 * Centralized types and constants used across FileTree components.
 */

// ── Sort Order ───────────────────────────────────────────────────────────────

export type SortOrder = 'name-asc' | 'name-desc' | 'mtime-asc' | 'mtime-desc' | 'ctime-asc' | 'ctime-desc'

export const SORT_OPTIONS: { value: SortOrder; label: string }[] = [
  { value: 'name-asc',   label: 'A → Z' },
  { value: 'name-desc',  label: 'Z → A' },
  { value: 'mtime-desc', label: 'Modified ↓' },
  { value: 'mtime-asc',  label: 'Modified ↑' },
  { value: 'ctime-desc', label: 'Created ↓' },
  { value: 'ctime-asc',  label: 'Created ↑' },
]

// ── App Settings ─────────────────────────────────────────────────────────────

export interface AppSettings {
  library_readonly: boolean
  move_confirm: string
  paths: { library_root: string; notes_path: string; generated_path: string }
  host_paths?: { library: string; notes: string; generated: string }
  excluded_extensions?: string[]
  tree_dim_extensions?: string[]
}

export const DEFAULT_SETTINGS: AppSettings = {
  library_readonly: true,
  move_confirm: 'confirm',
  paths: { library_root: '/library', notes_path: '/notes', generated_path: '/generated' },
}

// ── Move Operations ──────────────────────────────────────────────────────────

export interface PendingMove {
  src: string
  dest: string
}

// ── Context Menu ─────────────────────────────────────────────────────────────

export type ContextMenuItem = {
  label: string
  icon?: string
  action: () => void
  hintAfter?: string   // if set: show this hint for 2s then close, instead of closing immediately
  danger?: boolean
  disabled?: boolean
}

// ── File Icons ───────────────────────────────────────────────────────────────

export const EXT_ICONS: Record<string, string> = {
  '.md': '◦',
  '.pdf': '⬡',
  '.epub': '⬡',
  '.scriv': '⬡',
  '.docx': '⬡',
  '.doc': '⬡',
  '.png': '▣',
  '.jpg': '▣',
  '.jpeg': '▣',
  '.gif': '▣',
  '.webp': '▣',
  '.heic': '▣',
  '.mp3': '♪',
  '.mp4': '▶',
  '.mov': '▶',
  '.wav': '♪',
  '.zip': '⊞',
  '.tar': '⊞',
  '.gz': '⊞',
}

export const EXT_LABELS: Record<string, string> = {
  '.pdf': 'pdf',
  '.epub': 'epub',
  '.scriv': 'scriv',
  '.docx': 'docx',
  '.mp3': 'audio',
  '.mp4': 'video',
  '.mov': 'video',
  '.png': 'img',
  '.jpg': 'img',
  '.jpeg': 'img',
  '.gif': 'img',
  '.webp': 'img',
  '.heic': 'heic',
}

// ── Pagination ───────────────────────────────────────────────────────────────

/**
 * Large-folder pagination threshold.
 *
 * Folders with more children than this render only the first N rows on
 * expand, with a "+ M more" button revealing one more page per click.
 * Avoids the "click expand on a 3,000-file library/2024/, browser hangs"
 * scenario without introducing a virtualization layer.
 *
 * If pagination ever feels janky on real vaults, consider upgrading to
 * react-virtual (Strategy A): wrap the displayChildren render at
 * line ~733 in <VirtualList> when displayChildren.length > this
 * constant. The trade-off is losing the framer-motion height animation
 * on huge folders (acceptable — they were unusable before anyway).
 *
 * See `feat/filetree-large-folder-pagination` discussion (2026-04-28).
 */
export const LARGE_FOLDER_PAGE_SIZE = 100

// ── Expand Mode ──────────────────────────────────────────────────────────────

export type ExpandMode = boolean | null
