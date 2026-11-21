/**
 * Resolving an embedded asset's path, relative to the note that embeds it.
 *
 * `![](cat.png)` in a note used to render `<img src="cat.png">`, which the
 * browser resolves against the *app's* origin — so every embedded image in
 * every note was a 404. `/api/file/raw` has served vault bytes all along
 * (`api/routes/files.py`, and the Editor already uses it for standalone media);
 * nothing pointed at it.
 *
 * Extracted and tested per the maintainer notes § "Order-dependent logic comes out as
 * a tested pure function". The failure mode is the one that rule exists for: a
 * wrong answer here is a *plausible* path that renders a broken-image icon
 * rather than throwing, and the ordering genuinely matters — the absolute-URL
 * check must precede the mount check, which must precede relative resolution.
 */

/** The three mounts every vault has. Extra libraries are handled via `notePath`. */
const CORE_MOUNTS = ['notes', 'library', 'generated']

/** Schemes that address something outside the vault. Left untouched. */
const EXTERNAL_SCHEME_RE = /^(?:[a-z][a-z0-9+.-]*:)?\/\//i
const INLINE_SCHEME_RE = /^(?:data|blob):/i

/**
 * Resolve an embed `src` to a mount-prefixed vault path.
 *
 * Returns `null` when the src should be left exactly as written — an external
 * URL, an inline `data:` payload, or a relative path with no note to resolve
 * it against. `null` means "not ours", never "broken".
 */
export function resolveVaultPath(src: string, notePath?: string | null): string | null {
  const raw = (src ?? '').trim()
  if (!raw) return null

  // Order matters from here down.

  // 1. Anything addressing another origin, or carrying its own bytes, is not a
  //    vault path. Checked first: `https://x/notes/a.png` starts with a scheme
  //    and would otherwise fall through to the mount test below.
  if (EXTERNAL_SCHEME_RE.test(raw) || INLINE_SCHEME_RE.test(raw)) return null

  // 2. Already mount-prefixed — the form the rest of the app passes around.
  const firstSegment = raw.split('/')[0]
  const noteMount = notePath ? notePath.split('/')[0] : null
  if (CORE_MOUNTS.includes(firstSegment) || (noteMount && firstSegment === noteMount)) {
    return normalize(raw)
  }

  // 3. Everything else is relative to the note, so without one there is
  //    nothing to resolve against. Leave it alone rather than guess a mount.
  if (!notePath) return null

  // A leading slash means "from the top of my mount", the way Obsidian treats
  // vault-absolute links — not the filesystem root.
  const noteDir = notePath.split('/').slice(0, -1).join('/')
  const joined = raw.startsWith('/')
    ? `${noteMount}${raw}`
    : `${noteDir}/${raw}`

  const resolved = normalize(joined)
  // `..` that climbs past the mount root is not addressable, and the backend
  // would reject it anyway (`Settings.resolve()` rejects traversal). Returning
  // null leaves the original src visible rather than emitting a URL that 400s.
  if (!resolved || resolved.split('/')[0] !== noteMount) return null
  return resolved
}

/** Collapse `.` and `..` segments. Returns '' if the path climbs above root. */
function normalize(path: string): string {
  const out: string[] = []
  for (const segment of path.split('/')) {
    if (!segment || segment === '.') continue
    if (segment === '..') {
      if (out.length === 0) return ''
      out.pop()
      continue
    }
    out.push(segment)
  }
  return out.join('/')
}

/** The URL that serves a vault path's bytes. */
export function rawUrl(vaultPath: string): string {
  return `/api/file/raw?path=${encodeURIComponent(vaultPath)}`
}
