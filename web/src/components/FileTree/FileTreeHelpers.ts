/**
 * FileTree utility functions.
 *
 * Pure helper functions for file operations, sorting, and path manipulation.
 */

import type { TreeNode } from '../../lib/api'
import type { SortOrder, AppSettings } from './FileTreeTypes'

// ── File Extension ───────────────────────────────────────────────────────────

export function getExt(name: string): string {
  const idx = name.lastIndexOf('.')
  return idx >= 0 ? name.slice(idx).toLowerCase() : ''
}

// ── Sorting ──────────────────────────────────────────────────────────────────

export function sortNodes(nodes: TreeNode[], order: SortOrder): TreeNode[] {
  const sorted = [...nodes]
  sorted.sort((a, b) => {
    // Always directories before files
    if (a.type !== b.type) return a.type === 'directory' ? -1 : 1
    switch (order) {
      case 'name-asc':  return a.name.toLowerCase().localeCompare(b.name.toLowerCase())
      case 'name-desc': return b.name.toLowerCase().localeCompare(a.name.toLowerCase())
      case 'mtime-asc':  return (a.mtime ?? 0) - (b.mtime ?? 0)
      case 'mtime-desc': return (b.mtime ?? 0) - (a.mtime ?? 0)
      case 'ctime-asc':  return (a.ctime ?? 0) - (b.ctime ?? 0)
      case 'ctime-desc': return (b.ctime ?? 0) - (a.ctime ?? 0)
    }
  })
  return sorted
}

// ── Shell Quoting ────────────────────────────────────────────────────────────

/** Wrap a filesystem path in single quotes for safe terminal pasting.
 *  Handles embedded single quotes by ending the quote, inserting a literal ',
 *  then reopening the quote: foo'bar → 'foo'\''bar' */
export function shellQuote(path: string): string {
  return "'" + path.replace(/'/g, "'\\''") + "'"
}

// ── Host Path Resolution ─────────────────────────────────────────────────────

/**
 * Map a mount-prefixed vault path to the real filesystem path on the host.
 *
 * Named `useHostPath` until 2026-08-28, which was wrong twice over: it is a
 * plain function with no hooks in it, and the name made ESLint's
 * rules-of-hooks reject every call from a non-component — including the File
 * menu's Copy Path, which is exactly the kind of caller it should serve. A
 * `use` prefix is a claim about how a function may be called; this one could
 * not honour it.
 */
export function hostPath(nodePath: string, settings: AppSettings): string {
  const parts = nodePath.split('/')
  const mount = parts[0]
  const rest = parts.slice(1).join('/')
  // Prefer host-side paths (actual macOS filesystem paths) when available.
  // Falls back to Docker container paths if host paths weren't passed through.
  const hostRoots: Record<string, string> = {
    notes:     settings.host_paths?.notes     ?? settings.paths.notes_path,
    generated: settings.host_paths?.generated ?? settings.paths.generated_path,
    library:   settings.host_paths?.library   ?? settings.paths.library_root,
  }
  const root = hostRoots[mount]
  if (!root) return nodePath
  return rest ? `${root}/${rest}` : root
}

// ── Duplicate destination ────────────────────────────────────────────────────

/**
 * Where a duplicate of `path` should land, as a mount-prefixed path.
 *
 * Pure, and lifted out of `TreeNodeRow` so the file tree's Duplicate and the
 * File menu's cannot drift into two different answers for the same file. The
 * ordering is the substance: a `library/` file only stays in `library/` when
 * the vault is writable, and otherwise falls through to `notes/`. Reverse
 * those two branches and you get a plausible destination that fails on write
 * — the failure mode the maintainer notes describes for order-dependent logic.
 */
export function defaultDupeDest(path: string, vaultWritable: boolean): string {
  const parts = path.split('/')
  const filename = parts[parts.length - 1]
  const dotIdx = filename.lastIndexOf('.')
  const stem = dotIdx > 0 ? filename.slice(0, dotIdx) : filename
  const ext = dotIdx > 0 ? filename.slice(dotIdx) : ''
  const copyName = `copy-of-${stem}${ext}`
  const beside = [...parts.slice(0, -1), copyName].join('/')
  if (path.startsWith('notes/')) return beside
  // Library files: stay in library if writable, otherwise go to notes/.
  if (path.startsWith('library/') && vaultWritable) return beside
  return `notes/${copyName}`
}
