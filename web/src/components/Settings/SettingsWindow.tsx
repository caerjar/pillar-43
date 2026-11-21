import { useState, useEffect, useMemo } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api } from '../../lib/api'
import { useAppStore } from '../../stores/appStore'
import { Modal } from '../ui/Modal'
import { errorMessage } from '../../lib/errors'
import { SETTINGS_GROUPS as groups } from './groups'
import type { AppSettings } from './types'
import './SettingsPanel.css'

/**
 * Preferences — a window, not a pane.
 *
 * Settings used to take over the centre pane via `leftTab === 'settings'`.
 * That made it a destination you navigated *to* and had to navigate back
 * from, which is not how a Mac app behaves and is not what ⌘, promises.
 *
 * Visibility lives in `appStore.settingsOpen` and is deliberately NOT
 * persisted: a modal that survives a reload is one you cannot escape by
 * reloading, which was the latent failure of the persisted `leftTab:
 * 'settings'` this replaces.
 */
export function SettingsWindow() {
  const open = useAppStore((s) => s.settingsOpen)
  const requested = useAppStore((s) => s.settingsSection)
  const closeSettings = useAppStore((s) => s.closeSettings)

  const [s, setS] = useState<AppSettings | null>(null)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [active, setActive] = useState<string>(groups[0].id)
  // Bumped by Retry to re-run the load effect.
  const [loadAttempt, setLoadAttempt] = useState(0)
  const qc = useQueryClient()

  // Land on the requested group each time the window opens. Falls back to the
  // first group when the caller named one that no longer exists, rather than
  // rendering an empty pane.
  useEffect(() => {
    if (!open) return
    const wanted = groups.find((g) => g.id === requested)
    setActive(wanted ? wanted.id : groups[0].id)
  }, [open, requested])

  // Load only once the window is actually opened — this used to run on app
  // mount because the panel was always in the tree.
  //
  // The timeout is the point. `lib/api/_fetch.ts` sets no deadline on its
  // `fetch`, so a request that never settles leaves this window sitting on
  // "Loading…" with no error, no retry and no way to tell whether anything is
  // happening — which is indistinguishable, from the outside, from the app
  // having frozen. `GET /api/settings` does no network or disk work worth
  // measuring (~10ms against a real vault), so anything past 15s means the
  // backend is wedged or gone, and saying so beats an ellipsis.
  //
  // Advisory, not cancelling: if the slow request does eventually land, `s`
  // still populates and clears the message. Aborting would turn a slow-but-
  // fine backend into a hard failure.
  useEffect(() => {
    if (!open || s) return
    let cancelled = false
    setError(null)
    const timer = setTimeout(() => {
      if (!cancelled) {
        setError('Settings are taking longer than expected to load — the backend may be busy or unreachable.')
      }
    }, 15_000)
    api
      .appSettings()
      .then((r) => {
        if (cancelled) return
        setS(r)
        setError(null)
      })
      .catch((e) => {
        // `errorMessage` can return '', and `error ?? 'Loading…'` renders an
        // empty string as an empty string — a blank pane that looks like a
        // third, undocumented state. Fall back to something readable.
        if (!cancelled) setError(errorMessage(e) || 'Could not load settings.')
      })
      .finally(() => clearTimeout(timer))
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [open, s, loadAttempt])

  // Canonical write path — optimistic UI → api.updateSettings → setQueryData.
  // Per the maintainer notes § "Settings flow": every section uses this via the
  // `update` prop. Don't duplicate; don't inline.
  async function update(updates: Parameters<typeof api.updateSettings>[0]) {
    if (!s) return
    setS({ ...s, ...updates } as AppSettings)
    setSaving(true)
    setSaved(false)
    setError(null)
    try {
      const result = await api.updateSettings(updates)
      setS(result)
      qc.setQueryData(['app-settings'], result)
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } catch (e) {
      setError(errorMessage(e))
      setS(s)
    } finally {
      setSaving(false)
    }
  }

  const group = useMemo(
    () => groups.find((g) => g.id === active) ?? groups[0],
    [active],
  )

  return (
    <Modal
      open={open}
      onClose={closeSettings}
      title="Settings"
      width="min(1040px, calc(100vw - 96px))"
      bodyPadding={0}
      contentStyle={{ height: 'min(720px, calc(100vh - 96px))', display: 'flex', flexDirection: 'column' }}
    >
      <div className="sp-window">
        <nav className="sp-window__nav" aria-label="Settings sections">
          {groups.map((g) => (
            <button
              key={g.id}
              type="button"
              className={`sp-window__navitem${g.id === active ? ' sp-window__navitem--active' : ''}`}
              aria-current={g.id === active ? 'page' : undefined}
              onClick={() => setActive(g.id)}
            >
              {g.title}
            </button>
          ))}
        </nav>

        <div className="sp-window__content">
          <div className="sp-window__status">
            {saving && <span className="sp-status-saving">Saving…</span>}
            {!saving && saved && <span className="sp-status-saved">✓ Saved</span>}
            {error && <span className="sp-status-error" title={error}>Error</span>}
          </div>

          {s ? (
            <>
              <h2 className="sp-group__title">{group.title}</h2>
              <div className="sp-group__body">{group.render({ s, update })}</div>
            </>
          ) : (
            <div className="sp-panel-loading">
              {error ? (
                <>
                  <div>{error}</div>
                  <button
                    type="button"
                    className="sp-btn-test sp-btn-test--idle"
                    style={{ marginTop: 'var(--space-3)' }}
                    onClick={() => setLoadAttempt((n) => n + 1)}
                  >
                    Retry
                  </button>
                </>
              ) : (
                'Loading…'
              )}
            </div>
          )}

          <div className="sp-config-note">
            <div className="sp-config-note__text">
              Settings are saved on this machine.
            </div>
          </div>

          {error && s && <div className="sp-panel-error">{error}</div>}
        </div>
      </div>
    </Modal>
  )
}
