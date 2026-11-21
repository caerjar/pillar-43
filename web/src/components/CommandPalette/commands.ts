/**
 * Command Palette command registry.
 *
 * Each command has an id, a section, a title (what's shown), optional
 * keywords (what's matched against, in addition to title), and an `action`
 * called when the user picks it. Actions get a context object so they can
 * call into stores and the api.
 */
import type { LeftTab } from '../../stores/appStore'
import { DESTINATIONS } from '../../lib/menu/menuModel'

export type CommandSection = 'navigate' | 'view' | 'theme' | 'recent'

export interface DynamicCommandData {
  recentFiles?: string[]
  /** False for a writer: Settings answers 404 for them, so no entry. Default true. */
  canOpenSettings?: boolean
}

export interface CommandCtx {
  setLeftTab: (tab: LeftTab) => void
  /** Open the Preferences window, optionally on a named group (see
   *  `Settings/groups.tsx`). Settings is not a `LeftTab` — it is a window. */
  openSettings: (section?: string) => void
  setCurrentFile: (path: string | null) => void
  toggleFocusMode: () => void
  toggleLightMode: () => void
  toast: { success: (m: string) => void; error: (m: string) => void; info: (m: string) => void }
}

export interface Command {
  id: string
  section: CommandSection
  title: string
  /** Extra search keywords. Title is always matched too. */
  keywords?: string[]
  /** Optional shortcut hint shown to the right of the row. */
  shortcut?: string
  action: (ctx: CommandCtx) => void | Promise<void>
}

export function buildCommands(dynamic: DynamicCommandData = {}): Command[] {
  const commands: Command[] = [
    ...DESTINATIONS.map<Command>((d) => ({
      // The model's own id (`go.files`): the string the native macOS menu
      // sends back through `pillar43:menu`.
      id: d.id,
      section: 'navigate',
      title: `Switch to ${d.label}`,
      keywords: d.keywords,
      action: ({ setLeftTab }) => setLeftTab(d.tab),
    })),
    ...(dynamic.canOpenSettings === false ? [] : [{
      id: 'app.settings',
      section: 'navigate' as const,
      title: 'Open Settings',
      keywords: ['preferences', 'config', 'options'],
      action: ({ openSettings }: CommandCtx) => openSettings(),
    }]),
    {
      id: 'view.focus-mode',
      section: 'view',
      title: 'Toggle focus mode',
      shortcut: '⌘⇧F',
      action: ({ toggleFocusMode }) => toggleFocusMode(),
    },
    {
      id: 'theme.light-dark',
      section: 'theme',
      title: 'Toggle light/dark mode',
      action: ({ toggleLightMode }) => toggleLightMode(),
    },
  ]
  for (const path of dynamic.recentFiles ?? []) {
    const stem = path.split('/').pop() ?? path
    commands.push({
      id: `recent.${path}`,
      section: 'recent',
      title: `Recent: ${stem}`,
      keywords: ['recent', path],
      action: ({ setCurrentFile }) => setCurrentFile(path),
    })
  }
  return commands
}

/**
 * Score a command against a query. Higher is better. Returns -1 if no match.
 *
 * Scoring:
 *   - exact title prefix match: very high
 *   - all query chars present in order in title: medium-high
 *   - all query chars in keywords: medium
 *   - substring match: low
 */
export function scoreCommand(cmd: Command, query: string): number {
  if (!query) return 0
  const q = query.toLowerCase()
  const title = cmd.title.toLowerCase()

  if (title === q) return 1000
  if (title.startsWith(q)) return 800
  if (title.includes(q)) return 500

  // Subsequence match in title
  let qi = 0
  for (let i = 0; i < title.length && qi < q.length; i++) {
    if (title[i] === q[qi]) qi++
  }
  if (qi === q.length) return 200

  // Keyword exact/contains
  for (const kw of cmd.keywords ?? []) {
    if (kw.toLowerCase().includes(q)) return 100
  }

  return -1
}
