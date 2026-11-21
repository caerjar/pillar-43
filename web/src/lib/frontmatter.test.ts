import { describe, it, expect } from 'vitest'
import { splitFrontmatter } from './frontmatter'

describe('splitFrontmatter', () => {
  it('reads the shape the vault actually contains', () => {
    // Taken from a real distilled-session note.
    const raw = [
      '---',
      'session_id: e311ea18-7f35-4118-a8ee-a4404fd1296a',
      'date: 2026-08-08',
      'duration_min: 0',
      'ttl: 30d',
      'auto_distilled: true',
      '---',
      '',
      '# The note itself',
    ].join('\n')

    const { properties, body } = splitFrontmatter(raw)

    expect(properties).toEqual([
      { key: 'session_id', value: 'e311ea18-7f35-4118-a8ee-a4404fd1296a' },
      { key: 'date', value: '2026-08-08' },
      { key: 'duration_min', value: '0' },
      { key: 'ttl', value: '30d' },
      { key: 'auto_distilled', value: 'true' },
    ])
    expect(body).toBe('\n# The note itself')
  })

  describe('leaves the note alone when there is no frontmatter', () => {
    it('a plain note', () => {
      const raw = '# Title\n\nSome text.\n'
      expect(splitFrontmatter(raw)).toEqual({ properties: [], body: raw })
    })

    it('a horizontal rule further down the note', () => {
      // The case that matters most: `---` mid-document is a rule, and reading
      // it as frontmatter would silently eat the top of the note.
      const raw = '# Title\n\nIntro.\n\n---\n\nAfter the rule.\n'
      expect(splitFrontmatter(raw)).toEqual({ properties: [], body: raw })
    })

    it('an unclosed fence', () => {
      const raw = '---\nkey: value\n\nno closing fence\n'
      expect(splitFrontmatter(raw).properties).toEqual([])
      expect(splitFrontmatter(raw).body).toBe(raw)
    })

    it('a fence containing nothing parseable', () => {
      // Better to show the raw block than to hide content behind an empty
      // table the user cannot open.
      const raw = '---\n???\n---\n\nBody.\n'
      expect(splitFrontmatter(raw).properties).toEqual([])
      expect(splitFrontmatter(raw).body).toBe(raw)
    })

    it('an empty string', () => {
      expect(splitFrontmatter('')).toEqual({ properties: [], body: '' })
    })
  })

  describe('values', () => {
    it('unwraps an inline list', () => {
      const { properties } = splitFrontmatter('---\ntags: [herbs, grief]\n---\nx')
      expect(properties[0]).toEqual({ key: 'tags', value: ['herbs', 'grief'] })
    })

    it('unwraps an empty inline list', () => {
      const { properties } = splitFrontmatter('---\ntags: []\n---\nx')
      expect(properties[0]).toEqual({ key: 'tags', value: [] })
    })

    it('reads a dash list on following lines', () => {
      const raw = '---\ntags:\n  - herbs\n  - grief\nstatus: alive\n---\nx'
      const { properties } = splitFrontmatter(raw)
      expect(properties).toEqual([
        { key: 'tags', value: ['herbs', 'grief'] },
        { key: 'status', value: 'alive' },
      ])
    })

    it('strips surrounding quotes', () => {
      const { properties } = splitFrontmatter('---\ntitle: "On Grief"\nalt: \'x\'\n---\nb')
      expect(properties).toEqual([
        { key: 'title', value: 'On Grief' },
        { key: 'alt', value: 'x' },
      ])
    })

    it('keeps a colon inside a value', () => {
      // Splitting on the last colon instead of the first would truncate URLs.
      const { properties } = splitFrontmatter('---\nsource: https://example.com/a\n---\nb')
      expect(properties[0]).toEqual({ key: 'source', value: 'https://example.com/a' })
    })

    it('skips comments and blank lines', () => {
      const raw = '---\n# a comment\n\nkey: value\n---\nb'
      expect(splitFrontmatter(raw).properties).toEqual([{ key: 'key', value: 'value' }])
    })

    it('skips a bare key with nothing under it', () => {
      // An empty row tells the reader nothing and costs a line.
      const raw = '---\nempty:\nkey: value\n---\nb'
      expect(splitFrontmatter(raw).properties).toEqual([{ key: 'key', value: 'value' }])
    })
  })

  it('handles CRLF line endings', () => {
    const raw = '---\r\nkey: value\r\n---\r\n# Body'
    const { properties, body } = splitFrontmatter(raw)
    expect(properties).toEqual([{ key: 'key', value: 'value' }])
    expect(body).toBe('# Body')
  })
})
