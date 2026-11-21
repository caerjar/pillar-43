/**
 * The menu model: the one definition both surfaces read.
 *
 * The failures these catch are all silent. A destination missing from `Go` is
 * a view you can no longer reach from the menu, with nothing in the console.
 * A chord advertised in the UI but absent from the model is a keystroke that
 * does nothing.
 */
import { describe, it, expect, vi } from 'vitest'
import { buildMenus, menuActions, DESTINATIONS, acceleratorToCombo } from './menuModel'
import type { CommandCtx } from '../../components/CommandPalette/commands'

const host = {
  openSearch: vi.fn(),
  openCommandPalette: vi.fn(),
  goBack: vi.fn(),
  goForward: vi.fn(),
}

const menus = buildMenus(host)
const actions = menuActions(menus)

describe('menu model', () => {
  it('has the menus the native builder expects, in order', () => {
    // The native bar is assembled by walking this list.
    expect(menus.map((m) => m.label)).toEqual(['Pillar-43', 'Go'])
  })

  it('names the destinations that exist', () => {
    expect(DESTINATIONS.map((d) => d.label)).toEqual(['Ask', 'Files'])
  })

  it('binds each accelerator to exactly one action', () => {
    const accels = actions.map((a) => a.accelerator).filter(Boolean)
    expect(new Set(accels).size).toBe(accels.length)
  })

  it('gives every leaf a unique id', () => {
    // Ids are what the native menu sends back through `pillar43:menu`; a
    // duplicate would fire whichever action `find` reached first.
    const ids = actions.map((a) => a.id)
    expect(new Set(ids).size).toBe(ids.length)
  })

  it('puts every destination in the Go menu', () => {
    const go = menus.find((m) => m.id === 'go')!
    const goIds = go.items.filter((i) => i !== 'separator').map((i) => (i as { id: string }).id)
    for (const d of DESTINATIONS) {
      expect(goIds, `${d.label} missing from Go`).toContain(d.id)
    }
  })

  it('gives every destination a chord, and never the same one twice', () => {
    const chords = actions.map((a) => a.chord).filter(Boolean)
    expect(new Set(chords).size).toBe(chords.length)
    for (const d of DESTINATIONS) {
      expect(d.chord, `${d.label} has no chord`).toMatch(/^g [a-z]$/)
    }
  })

  it('does not put a chord on anything that already has a ⌘ accelerator', () => {
    for (const a of actions) {
      expect(a.chord && a.accelerator, `${a.id} advertises both`).toBeFalsy()
    }
  })

  it('Files leaves the open file alone', () => {
    // Picking Files while reading a note must not close the note.
    const ctx = { setCurrentFile: vi.fn(), setLeftTab: vi.fn() } as unknown as CommandCtx
    actions.find((a) => a.id === 'go.files')!.run(ctx)
    expect(ctx.setCurrentFile).not.toHaveBeenCalled()
    expect(ctx.setLeftTab).toHaveBeenCalledWith('files')
  })
})

describe('accelerators reach the page, not just the native menu', () => {
  // The native menu binds accelerators on macOS; the browser build has no menu
  // to bind them, so App.tsx registers every one with useGlobalKeyboard.
  it('translates every accelerator into a combo the key handler speaks', () => {
    for (const a of actions) {
      if (!a.accelerator) continue
      const combo = acceleratorToCombo(a.accelerator)
      expect(combo, `${a.id}`).toMatch(/^mod(\+shift)?(\+alt)?\+.+$/)
      expect(combo).toBe(combo.toLowerCase())
    }
  })

  it('maps the modifier spellings Tauri uses', () => {
    expect(acceleratorToCombo('CmdOrCtrl+,')).toBe('mod+,')
    expect(acceleratorToCombo('CmdOrCtrl+Shift+F')).toBe('mod+shift+f')
    expect(acceleratorToCombo('CmdOrCtrl+[')).toBe('mod+[')
  })
})

describe('Settings is a window, not a tab', () => {
  it('opens the Preferences window and never touches the left rail', () => {
    const ctx = { openSettings: vi.fn(), setLeftTab: vi.fn() } as unknown as CommandCtx
    actions.find((a) => a.id === 'app.settings')!.run(ctx)
    expect(ctx.openSettings).toHaveBeenCalled()
    expect(ctx.setLeftTab).not.toHaveBeenCalled()
  })
})
