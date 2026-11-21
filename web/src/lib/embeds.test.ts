import { describe, it, expect } from 'vitest'
import { resolveVaultPath, rawUrl } from './embeds'

const NOTE = 'notes/projects/plan.md'

describe('resolveVaultPath', () => {
  describe('leaves alone what is not ours', () => {
    it.each([
      'https://example.com/cat.png',
      'http://example.com/cat.png',
      '//example.com/cat.png',
      'data:image/png;base64,iVBORw0KGgo=',
      'blob:http://localhost/abc',
    ])('%s', (src) => {
      expect(resolveVaultPath(src, NOTE)).toBeNull()
    })

    it('checks the scheme before the mount name', () => {
      // The ordering case. `https://cdn/notes/x.png` has "https:" first but
      // would match the mount test if that ran first, and we would rewrite
      // someone else's URL into a vault path that does not exist.
      expect(resolveVaultPath('https://cdn.example.com/notes/x.png', NOTE)).toBeNull()
    })

    it('returns null for an empty or blank src', () => {
      expect(resolveVaultPath('', NOTE)).toBeNull()
      expect(resolveVaultPath('   ', NOTE)).toBeNull()
    })
  })

  describe('mount-prefixed paths pass through', () => {
    it.each([
      ['notes/a/b.png', 'notes/a/b.png'],
      ['library/scans/p.jpg', 'library/scans/p.jpg'],
      ['generated/chart.svg', 'generated/chart.svg'],
    ])('%s', (src, expected) => {
      expect(resolveVaultPath(src, NOTE)).toBe(expected)
    })

    it('resolves them with no note at all', () => {
      // Dispatch cards and AI messages render markdown with no containing file.
      expect(resolveVaultPath('generated/chart.svg', null)).toBe('generated/chart.svg')
    })

    it("accepts an extra library when that is the note's own mount", () => {
      // Extra libraries have user-chosen names and cannot be enumerated here,
      // so a bare `mybooks/…` is only read as a mount for notes living in it.
      expect(resolveVaultPath('mybooks/cover.png', 'mybooks/x.md')).toBe('mybooks/cover.png')
    })

    it('reads an unknown first segment as a subdirectory, not a mount', () => {
      // From a note elsewhere, `mybooks/cover.png` is an ordinary relative
      // path — a `mybooks/` folder beside the note. Guessing "mount" here
      // would silently point at a different file than the one written.
      expect(resolveVaultPath('mybooks/cover.png', NOTE)).toBe('notes/projects/mybooks/cover.png')
    })
  })

  describe('relative paths resolve against the note', () => {
    it('resolves a sibling', () => {
      expect(resolveVaultPath('cat.png', NOTE)).toBe('notes/projects/cat.png')
    })

    it('resolves an explicit ./', () => {
      expect(resolveVaultPath('./cat.png', NOTE)).toBe('notes/projects/cat.png')
    })

    it('climbs with ..', () => {
      expect(resolveVaultPath('../assets/cat.png', NOTE)).toBe('notes/assets/cat.png')
    })

    it('treats a leading slash as the top of the mount, not the filesystem', () => {
      // Obsidian's vault-absolute form. Reading it as a filesystem path would
      // produce '/assets/cat.png' and a 404.
      expect(resolveVaultPath('/assets/cat.png', NOTE)).toBe('notes/assets/cat.png')
    })

    it('handles a note at the mount root', () => {
      expect(resolveVaultPath('cat.png', 'notes/top.md')).toBe('notes/cat.png')
    })

    it('leaves a relative path alone when there is no note', () => {
      expect(resolveVaultPath('cat.png', null)).toBeNull()
      expect(resolveVaultPath('cat.png', undefined)).toBeNull()
    })
  })

  describe('refuses to climb out of the mount', () => {
    it.each([
      '../../../etc/passwd',
      '../../secrets.png',
      '/../escape.png',
    ])('%s', (src) => {
      // The backend rejects traversal anyway (Settings.resolve()), so this is
      // depth rather than the only defence — but emitting a URL we know will
      // 400 would replace a visible src with an invisible failure.
      expect(resolveVaultPath(src, NOTE)).toBeNull()
    })

    it('allows climbing to the mount root but no further', () => {
      expect(resolveVaultPath('../cat.png', NOTE)).toBe('notes/cat.png')
      expect(resolveVaultPath('../../cat.png', NOTE)).toBeNull()
    })
  })
})

describe('rawUrl', () => {
  it('points at the endpoint that already serves vault bytes', () => {
    expect(rawUrl('notes/a.png')).toBe('/api/file/raw?path=notes%2Fa.png')
  })

  it('encodes spaces and other path characters', () => {
    expect(rawUrl('notes/my file.png')).toBe('/api/file/raw?path=notes%2Fmy%20file.png')
  })
})
