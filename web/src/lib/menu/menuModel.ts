/**
 * The menu, defined once.
 *
 * Two surfaces render this: the in-app `MenuBar` (browser/Docker) and the
 * native macOS menu the Tauri shell builds (`desktop/src-tauri/src/menu.rs`).
 * Neither owns behaviour: adding an item here gives both surfaces the item,
 * and `scripts/codegen-menu` keeps the Rust side from drifting by generating
 * its labels from this file.
 *
 * The command palette reads `DESTINATIONS` from here, and
 * `commands.test.ts` walks it and fails if a destination has no command.
 *
 * ## Accelerators vs chords
 *
 * - `accelerator`: a single combo the native menu binds and displays
 *   (`CmdOrCtrl+,`). Also handled in-page by App.tsx for the browser.
 * - `chord`: a two-key sequence (`g f`) handled by `useGlobalKeyboard`'s
 *   chord engine in BOTH runtimes. Browsers reserve the digit combos, so
 *   navigation uses chords. macOS menus cannot display a sequence, so native
 *   `Go` items show no accelerator while the in-app menu shows the chord.
 */
import type { CommandCtx } from '../../components/CommandPalette/commands'
import type { LeftTab } from '../../stores/appStore'

/**
 * `CmdOrCtrl+Shift+F` → `mod+shift+f`, the combo grammar `useGlobalKeyboard`
 * speaks.
 *
 * Every accelerator the model advertises has to be handled in the page as well
 * as by the native menu, because the browser build has no native menu at all.
 * Before this existed, ⌘N and ⌘, were displayed in both menus and bound in
 * neither — the same advertised-but-dead failure the chords had.
 */
export function acceleratorToCombo(accel: string): string {
  return accel
    .split('+')
    .map((p) => {
      const k = p.trim().toLowerCase()
      if (k === 'cmdorctrl' || k === 'cmd' || k === 'super' || k === 'ctrl') return 'mod'
      return k
    })
    .join('+')
}

/** A leaf item. `run` is what actually happens; everything else is display. */
export interface MenuAction {
  /** Stable. Shared with the command palette where the two overlap, and it is
   *  this string the native menu sends back through `pillar43:menu`. */
  id: string
  label: string
  /** Single combo — bound and displayed by the native menu. */
  accelerator?: string
  /** Two-key sequence — displayed in-app, handled by the chord engine. */
  chord?: string
  /** Extra search terms, for the command palette. */
  keywords?: string[]
  run: (ctx: CommandCtx) => void | Promise<void>
}

export type MenuEntry = MenuAction | 'separator'

export interface MenuDef {
  id: string
  label: string
  items: MenuEntry[]
}

/**
 * Where you can go. Read by the `Go` menu and the command palette.
 * `tab` is the `leftTab` store value.
 */
export const DESTINATIONS: Array<{
  id: string
  tab: LeftTab
  label: string
  chord: string
  keywords?: string[]
}> = [
  { id: 'go.ask', tab: 'ask', label: 'Ask', chord: 'g a', keywords: ['question', 'archive', 'search'] },
  { id: 'go.files', tab: 'files', label: 'Files', chord: 'g f', keywords: ['tree', 'explorer'] },
]

/** Extra actions the host page must provide: things no store setter covers. */
export interface MenuHostActions {
  openSearch: () => void
  openCommandPalette: () => void
  goBack: () => void
  goForward: () => void
  /** False for a writer: the backend answers 404 on /api/settings, so the
   *  Settings entry (and its ⌘, accelerator) is not offered. Default true. */
  canOpenSettings?: boolean
}

export function buildMenus(host: MenuHostActions): MenuDef[] {
  const destination = (d: (typeof DESTINATIONS)[number]): MenuAction => ({
    id: d.id,
    label: d.label,
    chord: d.chord,
    keywords: d.keywords,
    run: ({ setLeftTab }) => setLeftTab(d.tab),
  })

  const menus: MenuDef[] = [
    {
      // The macOS application menu. Rust wraps these with About / Services /
      // Hide / Quit; the in-app bar renders them as a plain dropdown, because
      // a browser has no application menu to put them in.
      id: 'app',
      label: 'Pillar-43',
      items: [
        ...(host.canOpenSettings === false
          ? []
          : [{ id: 'app.settings', label: 'Settings…', accelerator: 'CmdOrCtrl+,', run: ({ openSettings }: CommandCtx) => openSettings() }]),
      ],
    },
    {
      id: 'go',
      label: 'Go',
      items: [
        { id: 'go.back', label: 'Back', accelerator: 'CmdOrCtrl+[', run: () => host.goBack() },
        { id: 'go.forward', label: 'Forward', accelerator: 'CmdOrCtrl+]', run: () => host.goForward() },
        'separator',
        // Ellipses because each opens a surface that then asks for input.
        { id: 'go.search', label: 'Search…', accelerator: 'CmdOrCtrl+K', run: () => host.openSearch() },
        { id: 'go.command-palette', label: 'Command Palette…', accelerator: 'CmdOrCtrl+P', run: () => host.openCommandPalette() },
        'separator',
        ...DESTINATIONS.map(destination),
      ],
    },
  ]
  // A menu left with no items (the app menu for a writer) is not shown.
  return menus.filter((m) => m.items.length > 0)
}

/** Flatten to leaves: used by the palette and by the native-menu dispatcher. */
export function menuActions(menus: MenuDef[]): MenuAction[] {
  return menus.flatMap((m) => m.items.filter((i): i is MenuAction => i !== 'separator'))
}
