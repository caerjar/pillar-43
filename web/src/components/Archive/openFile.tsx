/**
 * Opening a whole file from Ask, Explore or People. An admin has the Files tab
 * and lands there. Everyone else has no Files tab, so the file opens in the
 * same viewer with a "Back to <view>" control that returns to the view it
 * came from, with its result still on screen.
 */
import { useAppStore } from '../../stores/appStore'
import { useSessionStore } from '../../stores/sessionStore'
import { Button } from './Button'
import { useArchiveViews } from './viewStore'

type View = 'ask' | 'explore' | 'people'
const LABEL: Record<View, string> = { ask: 'Ask', explore: 'Explore', people: 'People' }

export function useOpenFile() {
  const setCurrentFile = useAppStore((s) => s.setCurrentFile)
  const setLeftTab = useAppStore((s) => s.setLeftTab)
  const setPdfTarget = useAppStore((s) => s.setPdfTarget)
  const isAdmin = useSessionStore((s) => s.role === 'admin')
  return (path: string, page?: number | null, text?: string) => {
    const from = useAppStore.getState().leftTab
    useArchiveViews.getState().set({ returnTo: !isAdmin && (from === 'ask' || from === 'explore' || from === 'people') ? from : null })
    setPdfTarget(page ? (text ? { path, page, text } : { path, page }) : null)
    setCurrentFile(path)
    setLeftTab('files')
  }
}

/** Above the viewer, for a file a non-admin opened from an org view. */
export function BackToView() {
  const returnTo = useArchiveViews((s) => s.returnTo)
  const set = useArchiveViews((s) => s.set)
  const setCurrentFile = useAppStore((s) => s.setCurrentFile)
  const setLeftTab = useAppStore((s) => s.setLeftTab)
  const setPdfTarget = useAppStore((s) => s.setPdfTarget)
  if (!returnTo) return null
  return (
    <div style={{ padding: '6px 12px', borderBottom: '1px solid var(--border)', background: 'var(--bg-panel)', flexShrink: 0 }}>
      <Button
        onClick={() => {
          setPdfTarget(null)
          setCurrentFile(null)
          setLeftTab(returnTo)
          set({ returnTo: null })
        }}
      >
        Back to {LABEL[returnTo]}
      </Button>
    </div>
  )
}
