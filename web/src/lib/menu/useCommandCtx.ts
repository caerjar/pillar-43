/**
 * The context every menu/palette action runs against.
 *
 * Extracted so the menu bar and the command palette cannot drift into two
 * slightly different sets of capabilities. `CommandPalette.tsx` built this
 * inline; if a second surface had built its own, the first divergence would
 * have been silent — an action working from one place and not the other.
 */
import { useMemo } from 'react'
import { useAppStore } from '../../stores/appStore'
import { useToast } from '../../components/ui/Toast'
import type { CommandCtx } from '../../components/CommandPalette/commands'

export function useCommandCtx(): CommandCtx {
  const setLeftTab = useAppStore((s) => s.setLeftTab)
  // A zustand setter is reference-stable, so this does not destabilise the memo.
  const openSettings = useAppStore((s) => s.openSettings)
  const setCurrentFile = useAppStore((s) => s.setCurrentFile)
  const toggleFocusMode = useAppStore((s) => s.toggleFocusMode)
  const lightMode = useAppStore((s) => s.lightMode)
  const setLightMode = useAppStore((s) => s.setLightMode)
  const toast = useToast()
  // Memoised, and that matters beyond tidiness. The chord bindings are derived
  // from this object and handed to `useGlobalKeyboard`, whose effect resets the
  // pending chord key when it re-registers. An unstable ctx would re-register
  // on every render — so a background refetch landing between the `g` and the
  // `f` would silently swallow the chord.
  return useMemo(
    () => ({
      setLeftTab,
      openSettings,
      setCurrentFile,
      toggleFocusMode,
      toggleLightMode: () => setLightMode(!lightMode),
      toast,
    }),
    [setLeftTab, openSettings, setCurrentFile, toggleFocusMode, lightMode, setLightMode, toast],
  )
}
