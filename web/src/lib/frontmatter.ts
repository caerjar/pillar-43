/**
 * Splitting YAML frontmatter off a note, for display.
 *
 * The backend writes frontmatter across many modules — transcripts, handwriting
 * captures, distilled sessions — and nothing on the frontend has ever parsed
 * it. `marked` rendered the opening `---` as a horizontal rule and the keys as
 * one run-on paragraph, so every note carrying metadata opened with a slab of
 * visible garbage. This is the read half of that: the keys become a properties
 * table and the body renders on its own.
 *
 * Deliberately NOT a YAML parser, and no YAML dependency for a display
 * concern. It reads the shapes the vault actually contains — `key: value`,
 * inline `[a, b]` lists, and `-` item lists — and treats anything it does not
 * recognise as an opaque string rather than guessing. A wrong guess would show
 * the user a value their file does not contain.
 */

export interface NoteProperty {
  key: string
  /** A single scalar, or the items of a list. */
  value: string | string[]
}

export interface SplitNote {
  properties: NoteProperty[]
  /** The note without its frontmatter block. Unchanged when there is none. */
  body: string
}

/** Frontmatter is only frontmatter at the very top of the file. */
const FENCE_RE = /^---[ \t]*\r?\n([\s\S]*?)\r?\n---[ \t]*(?:\r?\n|$)/

export function splitFrontmatter(raw: string): SplitNote {
  const text = raw ?? ''
  // A `---` further down is a horizontal rule, and treating it as frontmatter
  // would silently eat the top of someone's note.
  const match = text.match(FENCE_RE)
  if (!match) return { properties: [], body: text }

  const properties = parseBlock(match[1])
  // An unparseable block is left in the body rather than dropped. Showing the
  // raw text is worse than a table; showing nothing at all is worse than both.
  if (properties.length === 0) return { properties: [], body: text }

  return { properties, body: text.slice(match[0].length) }
}

function parseBlock(block: string): NoteProperty[] {
  const out: NoteProperty[] = []
  const lines = block.split(/\r?\n/)

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    if (!line.trim() || line.trimStart().startsWith('#')) continue

    // Indented lines belong to the key above; they are consumed there.
    if (/^\s/.test(line)) continue

    const sep = line.indexOf(':')
    if (sep <= 0) continue
    const key = line.slice(0, sep).trim()
    if (!key) continue
    const rest = line.slice(sep + 1).trim()

    if (rest) {
      const list = inlineList(rest)
      out.push({ key, value: list ?? scalar(rest) })
      continue
    }

    // `key:` with the items on following indented lines.
    const items: string[] = []
    while (i + 1 < lines.length && /^\s+-\s?/.test(lines[i + 1])) {
      items.push(scalar(lines[i + 1].replace(/^\s+-\s?/, '').trim()))
      i++
    }
    if (items.length > 0) out.push({ key, value: items })
    // A bare `key:` with nothing under it carries no information — skip it
    // rather than render an empty row.
  }

  return out
}

/** Strip surrounding quotes and unwrap an inline `[a, b]` list. */
function scalar(value: string): string {
  const v = value.trim()
  if (
    (v.startsWith('"') && v.endsWith('"') && v.length >= 2) ||
    (v.startsWith("'") && v.endsWith("'") && v.length >= 2)
  ) {
    return v.slice(1, -1)
  }
  return v
}

/** Unwrap an inline list, or return null when the value is not one. */
export function inlineList(value: string): string[] | null {
  const v = value.trim()
  if (!v.startsWith('[') || !v.endsWith(']')) return null
  const inner = v.slice(1, -1).trim()
  if (!inner) return []
  return inner.split(',').map((s) => scalar(s))
}
