/**
 * Tests for the command palette's registry.
 *
 * It is the third of three navigation surfaces (the rail, the Go menu and
 * ⌘P), so a silent behaviour change here is one the other two would not
 * catch. `scoreCommand`'s tiers are ordered, and a wrong order returns a
 * plausible ranking rather than an error.
 */
import { describe, it, expect, vi } from 'vitest'
import { buildCommands, scoreCommand, type Command, type CommandCtx } from './commands'

function ctx(over: Partial<CommandCtx> = {}): CommandCtx {
  return {
    setLeftTab: vi.fn(),
    openSettings: vi.fn(),
    setCurrentFile: vi.fn(),
    toggleFocusMode: vi.fn(),
    toggleLightMode: vi.fn(),
    toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
    ...over,
  } as CommandCtx
}

const byId = (cmds: Command[], id: string) => cmds.find((c) => c.id === id)

describe('buildCommands — the static registry', () => {
  it('gives every command a unique id', () => {
    // Ids key React rows and are how a command is located; a duplicate makes
    // whichever one `find` reaches first shadow the other.
    const ids = buildCommands().map((c) => c.id)
    expect(new Set(ids).size).toBe(ids.length)
  })

  it('routes each navigation command to its own tab', () => {
    // Ids are the menu model's (`go.files`), not the private `nav.files` this
    // file used before the two lists were merged. The model's ids are the ones
    // the native macOS menu sends back through `pillar43:menu`, so they are
    // the pair worth keeping; the palette's were internal.
    const cmds = buildCommands()
    for (const [id, tab] of [
      ['go.ask', 'ask'],
      ['go.files', 'files'],
    ] as const) {
      const c = ctx()
      byId(cmds, id)!.action(c)
      expect(c.setLeftTab, id).toHaveBeenCalledWith(tab)
    }
  })

  it('opens Settings as a window, never as a tab', () => {
    // Settings stopped being a `LeftTab` on 2026-08-30. A regression that put
    // it back would land the user on a rail tab that renders nothing.
    const c = ctx()
    byId(buildCommands(), 'app.settings')!.action(c)
    expect(c.openSettings).toHaveBeenCalled()
    expect(c.setLeftTab).not.toHaveBeenCalled()
  })

  it('wires the view and theme commands to their own toggles', () => {
    const cmds = buildCommands()
    const a = ctx()
    byId(cmds, 'view.focus-mode')!.action(a)
    expect(a.toggleFocusMode).toHaveBeenCalled()

    const b = ctx()
    byId(cmds, 'theme.light-dark')!.action(b)
    expect(b.toggleLightMode).toHaveBeenCalled()
  })
})

describe('dynamic commands', () => {
  it('offers recent files by stem, and opens the full path', () => {
    const cmds = buildCommands({ recentFiles: ['notes/deep/nested/note.md'] })
    const cmd = byId(cmds, 'recent.notes/deep/nested/note.md')!
    expect(cmd.title).toBe('Recent: note.md')
    const c = ctx()
    cmd.action(c)
    expect(c.setCurrentFile).toHaveBeenCalledWith('notes/deep/nested/note.md')
  })

  it('builds only the static set when given no dynamic data', () => {
    const cmds = buildCommands()
    expect(cmds.every((c) => c.section !== 'recent')).toBe(true)
  })
})

describe('scoreCommand — the tiers are ordered', () => {
  const cmd = (title: string, keywords?: string[]): Command => ({
    id: 'x', section: 'navigate', title, keywords, action: () => {},
  })

  it('returns 0 for an empty query so everything stays listed', () => {
    expect(scoreCommand(cmd('Switch to Files'), '')).toBe(0)
  })

  it('ranks exact over prefix over substring over subsequence over keyword', () => {
    // Written as one chain rather than five equality assertions: the absolute
    // numbers are an implementation detail, the ORDER is the contract. A
    // rewrite that renumbers the tiers is fine; one that reorders them makes
    // ⌘P return plausible-but-wrong rankings, with nothing throwing.
    const exact = scoreCommand(cmd('files'), 'files')
    const prefix = scoreCommand(cmd('files and folders'), 'files')
    const substring = scoreCommand(cmd('all files here'), 'files')
    const subsequence = scoreCommand(cmd('fabulous idle essays'), 'files')
    const keyword = scoreCommand(cmd('Switch to Tree', ['files']), 'files')
    expect(exact).toBeGreaterThan(prefix)
    expect(prefix).toBeGreaterThan(substring)
    expect(substring).toBeGreaterThan(subsequence)
    expect(subsequence).toBeGreaterThan(keyword)
    expect(keyword).toBeGreaterThan(0)
  })

  it('returns -1 when nothing matches', () => {
    expect(scoreCommand(cmd('Switch to Files', ['tree']), 'zzzz')).toBe(-1)
  })

  it('is case-insensitive on both sides', () => {
    expect(scoreCommand(cmd('Switch to Files'), 'SWITCH')).toBeGreaterThan(0)
    expect(scoreCommand(cmd('Switch to Files', ['TREE']), 'tree')).toBeGreaterThan(0)
  })
})

describe('⌘P reaches every destination the other two surfaces do', () => {
  // The gap this consolidation closes, asserted against the shared model
  // rather than a hand-copied list — a hardcoded expectation here would be a
  // fourth place to forget a destination.
  it('offers a command for every DESTINATION in the menu model', async () => {
    const { DESTINATIONS } = await import('../../lib/menu/menuModel')
    const cmds = buildCommands()
    for (const d of DESTINATIONS) {
      const hit = cmds.find((c) => c.id === d.id || c.title.includes(d.label))
      expect(hit, `${d.label} (${d.id}) is unreachable from ⌘P`).toBeTruthy()
    }
  })

  it('reaches Ask and Files by name', () => {
    const cmds = buildCommands()
    for (const label of ['ask', 'files']) {
      const hit = cmds.find((c) => scoreCommand(c, label) > 0)
      expect(hit, `typing "${label}" into ⌘P finds nothing`).toBeTruthy()
    }
  })
})
