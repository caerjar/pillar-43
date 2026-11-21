import type { ReactNode } from 'react'
import { Section } from './controls'
import { AiModelsSection } from './sections/AiModelsSection'
import { ExcludedTypesSection } from './sections/ExcludedTypesSection'
import { PathsSection } from './sections/PathsSection'
import { VaultHealthSection } from './sections/VaultHealthSection'
import type { AppSettings, UpdateFn } from './types'

export interface SettingsGroupCtx {
  s: AppSettings
  update: UpdateFn
}

export interface SettingsGroupDef {
  /** Stable id — used by `openSettings('ai')` and as the nav key. */
  id: string
  /** Sidebar label and the heading above the content pane. */
  title: string
  render: (ctx: SettingsGroupCtx) => ReactNode
}

/**
 * The Preferences window's groups, in order.
 *
 * ONE list, read by both the sidebar and the content pane. That is the point:
 * when the nav was JSX and the content was the same JSX, a group could only
 * ever be in both. Splitting them across two arrays is how you get an entry
 * that navigates to nothing, so they stay a single source here and
 * `SettingsWindow.test.tsx` pins that every entry renders something.
 *
 * The window renders ONE group at a time.
 */
export const SETTINGS_GROUPS: SettingsGroupDef[] = [
  {
    // Ollama only. No hosted provider, no routing.
    id: 'local-models',
    title: 'Local models',
    render: ({ s, update }) => <AiModelsSection s={s} update={update} />,
  },
  {
    id: 'storage',
    title: 'Storage',
    render: ({ s, update }) => (
      <>
        <Section title="Paths" />
        <PathsSection s={s} />

        <Section title="Workspace Health" />
        <VaultHealthSection />

        <Section title="Excluded file types" />
        <ExcludedTypesSection s={s} update={update} />
      </>
    ),
  },
]
