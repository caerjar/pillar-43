import DOMPurify from 'dompurify'
import { marked } from 'marked'
import { resolveVaultPath, rawUrl } from './embeds'

marked.setOptions({
  breaks: true,
  gfm: true,
})

// Convert [[Wikilinks]] and [[path|Label]] to markdown links before parsing.
// Angle brackets around the href allow spaces in note names (CommonMark spec).
function preprocessWikilinks(raw: string): string {
  return raw.replace(/\[\[([^\]|]+?)(?:\|([^\]]+?))?\]\]/g, (_, path: string, label?: string) => {
    // Strip trailing backslash — old thread files used [[path\|display]] where
    // \| escaped the pipe for markdown tables, leaving a trailing \ in the path.
    const cleanPath = path.trim().replace(/\\$/, '')
    const display = label ?? cleanPath
    return `[${display}](<${cleanPath}>)`
  })
}

const FILE_EXT_RE = /\.(md|pdf|epub|docx|doc|mp3|mp4|mov|jpg|jpeg|png|svg|gif|webp|wav|ogg|xlsx|xls)$/i

// A code span is a file ref if it ends in a known extension OR looks like a path (contains /).
function isFileRef(text: string): boolean {
  if (text.length > 200) return false
  return FILE_EXT_RE.test(text) || text.includes('/')
}

// Custom renderer: any non-http link is treated as an internal vault path.
// This covers notes/library/generated prefixed paths AND bare wikilink names.
// External links (http/https) open in a new tab.
// Code spans that look like file paths get a data-file-search attribute so the
// editor can navigate to them on click.
marked.use({
  renderer: {
    link({ href, text }: { href: string | null; text: string }) {
      if (!href) return text
      const isExternal = /^https?:\/\//.test(href)
      if (isExternal) {
        return `<a href="${href}" target="_blank" rel="noopener noreferrer">${text}</a>`
      }
      return `<a data-library-path="${href}" class="internal-link">${text}</a>`
    },
    codespan({ text }: { text: string }) {
      const escaped = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
      if (isFileRef(text)) {
        return `<code class="file-ref" data-file-search="${escaped}">${escaped}</code>`
      }
      return `<code>${escaped}</code>`
    },
  },
})

export interface RenderOptions {
  /**
   * The note being rendered, mount-prefixed. Lets `![](cat.png)` resolve
   * against the note's own folder. Omit for markdown with no containing file
   * (AI messages, the dispatch, task text) — mount-prefixed embeds still
   * resolve there; relative ones are left exactly as written.
   */
  notePath?: string | null
}

export function renderMarkdown(raw: string, opts: RenderOptions = {}): string {
  const html = marked.parse(preprocessWikilinks(raw)) as string
  const clean = DOMPurify.sanitize(html, {
    ADD_ATTR: ['data-library-path', 'data-file-search', 'target', 'rel'],
  })
  return resolveEmbedSrcs(clean, opts.notePath)
}

/**
 * Point every vault-relative `<img>` at the endpoint that serves vault bytes.
 *
 * Done as a pass over the *sanitized* HTML rather than inside a `marked`
 * renderer, for two reasons. It operates on what will actually be inserted, so
 * no markdown edge case can route an image around it; and `marked`'s renderers
 * are registered once at module scope, so per-call context (which note are we
 * in?) would have to arrive through a module-level variable — hidden state on a
 * function called from six places.
 */
function resolveEmbedSrcs(html: string, notePath?: string | null): string {
  // Cheap bail-out: most rendered markdown has no images at all.
  if (!html.includes('<img')) return html

  const doc = new DOMParser().parseFromString(html, 'text/html')
  let changed = false
  for (const img of Array.from(doc.images)) {
    const resolved = resolveVaultPath(img.getAttribute('src') ?? '', notePath)
    if (!resolved) continue
    img.setAttribute('src', rawUrl(resolved))
    // The vault path stays readable for anything that wants to act on the
    // image later (click-to-open), and for debugging a wrong resolution.
    img.setAttribute('data-vault-path', resolved)
    changed = true
  }
  return changed ? doc.body.innerHTML : html
}
