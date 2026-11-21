import { describe, it, expect } from 'vitest'
import { renderMarkdown } from './markdown'

// Access the preprocessor via the rendered output — we test observable behaviour,
// not the internal function directly.

describe('renderMarkdown — wikilinks', () => {
  it('converts [[Note Name]] to an internal link', () => {
    const html = renderMarkdown('[[Note Name]]')
    expect(html).toContain('data-library-path="Note Name"')
    expect(html).toContain('class="internal-link"')
    expect(html).toContain('>Note Name<')
  })

  it('converts [[path/to/file.md]] to an internal link with the path as label', () => {
    const html = renderMarkdown('[[path/to/file.md]]')
    expect(html).toContain('data-library-path="path/to/file.md"')
  })

  it('converts [[path/to/file.md|Label]] using the custom label', () => {
    const html = renderMarkdown('[[path/to/file.md|My Label]]')
    expect(html).toContain('data-library-path="path/to/file.md"')
    expect(html).toContain('>My Label<')
  })
})

describe('renderMarkdown — internal links', () => {
  it('treats library-prefixed links as internal', () => {
    const html = renderMarkdown('[a file](library/path/to/note.md)')
    expect(html).toContain('data-library-path="library/path/to/note.md"')
    expect(html).toContain('class="internal-link"')
    expect(html).not.toContain('href=')
    expect(html).not.toContain('target=')
  })

  it('treats notes-prefixed links as internal', () => {
    const html = renderMarkdown('[note](notes/thread/note.md)')
    expect(html).toContain('data-library-path="notes/thread/note.md"')
  })

  it('treats generated-prefixed links as internal', () => {
    const html = renderMarkdown('[scratch](generated/scratch.md)')
    expect(html).toContain('data-library-path="generated/scratch.md"')
  })

  it('treats bare non-http links as internal (wikilink by name)', () => {
    const html = renderMarkdown('[Cazimi](Cazimi)')
    expect(html).toContain('data-library-path="Cazimi"')
    expect(html).not.toContain('target="_blank"')
  })
})

describe('renderMarkdown — external links', () => {
  it('renders http links with target=_blank and rel=noopener', () => {
    const html = renderMarkdown('[example](http://example.com)')
    expect(html).toContain('href="http://example.com"')
    expect(html).toContain('target="_blank"')
    expect(html).toContain('rel="noopener noreferrer"')
    expect(html).not.toContain('data-library-path')
  })

  it('renders https links as external', () => {
    const html = renderMarkdown('[secure](https://example.com/page)')
    expect(html).toContain('href="https://example.com/page"')
    expect(html).toContain('target="_blank"')
  })
})

describe('renderMarkdown — standard markdown', () => {
  it('renders headings', () => {
    const html = renderMarkdown('# Hello')
    expect(html).toContain('<h1>Hello</h1>')
  })

  it('renders bold text', () => {
    const html = renderMarkdown('**bold**')
    expect(html).toContain('<strong>bold</strong>')
  })

  it('renders plain code spans without file-ref class', () => {
    const html = renderMarkdown('`inline code`')
    expect(html).toContain('<code>inline code</code>')
    expect(html).not.toContain('file-ref')
  })
})

describe('renderMarkdown — file-ref code spans', () => {
  it('marks .md filenames as file-ref', () => {
    const html = renderMarkdown('`Saturn_Roof_&_Pillars.md`')
    expect(html).toContain('class="file-ref"')
    expect(html).toContain('data-file-search="Saturn_Roof_&amp;_Pillars.md"')
  })

  it('marks .pdf filenames as file-ref', () => {
    const html = renderMarkdown('`mf_hd.pdf`')
    expect(html).toContain('class="file-ref"')
    expect(html).toContain('data-file-search="mf_hd.pdf"')
  })

  it('marks path-like code spans (contains /) as file-ref', () => {
    const html = renderMarkdown('`Research/Astrology/Horary 1`')
    expect(html).toContain('class="file-ref"')
    expect(html).toContain('data-file-search="Research/Astrology/Horary 1"')
  })

  it('does not mark plain code words as file-ref', () => {
    const html = renderMarkdown('`npm install`')
    expect(html).not.toContain('file-ref')
  })

  it('does not mark short code words as file-ref', () => {
    const html = renderMarkdown('`const x = 1`')
    expect(html).not.toContain('file-ref')
  })
})

describe('embedded images', () => {
  it('points a relative image at the endpoint that serves vault bytes', () => {
    // The bug: this rendered <img src="cat.png">, which the browser resolved
    // against the app's origin, so every embedded image in every note 404'd.
    const html = renderMarkdown('![a cat](cat.png)', { notePath: 'notes/projects/plan.md' })
    expect(html).toContain('src="/api/file/raw?path=notes%2Fprojects%2Fcat.png"')
    expect(html).toContain('alt="a cat"')
  })

  it('resolves the ![[wikilink]] embed form too', () => {
    // `![[x.png]]` already became an <img> via the wikilink preprocessor — it
    // just carried the same broken src.
    const html = renderMarkdown('![[diagram.png]]', { notePath: 'notes/plan.md' })
    expect(html).toContain('src="/api/file/raw?path=notes%2Fdiagram.png"')
  })

  it('leaves external images untouched', () => {
    const html = renderMarkdown('![x](https://example.com/a.png)', { notePath: 'notes/p.md' })
    expect(html).toContain('src="https://example.com/a.png"')
    expect(html).not.toContain('/api/file/raw')
  })

  it('leaves a relative image alone when there is no containing note', () => {
    // AI messages and the dispatch render markdown with no file behind them;
    // guessing a mount there would point at a file the author never named.
    const html = renderMarkdown('![x](cat.png)')
    expect(html).toContain('src="cat.png"')
    expect(html).not.toContain('/api/file/raw')
  })

  it('still resolves a mount-prefixed image with no containing note', () => {
    const html = renderMarkdown('![x](generated/chart.svg)')
    expect(html).toContain('src="/api/file/raw?path=generated%2Fchart.svg"')
  })

  it('keeps the vault path readable on the element', () => {
    const html = renderMarkdown('![x](cat.png)', { notePath: 'notes/p.md' })
    expect(html).toContain('data-vault-path="notes/cat.png"')
  })

  it('does not emit a URL for a path that climbs out of the mount', () => {
    const html = renderMarkdown('![x](../../../etc/passwd)', { notePath: 'notes/p.md' })
    expect(html).not.toContain('/api/file/raw')
  })

  it('leaves markdown with no images byte-identical', () => {
    // The rewrite pass must be a no-op for the overwhelmingly common case,
    // including the HTML re-serialisation a DOMParser round-trip would do.
    const src = '# Title\n\nSome **bold** text and a [link](notes/a.md).\n'
    expect(renderMarkdown(src, { notePath: 'notes/p.md' })).toBe(renderMarkdown(src))
  })
})
