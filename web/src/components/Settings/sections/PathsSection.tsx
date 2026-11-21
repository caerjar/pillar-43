import { useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api } from '../../../lib/api'
import { PathRow } from '../PathRow'
import { errorMessage } from '../../../lib/errors'

type AppSettings = Awaited<ReturnType<typeof api.appSettings>>

/**
 * Paths section + the "restart required" banner above the panel body.
 *
 * Banner state (`pendingPaths`, `pendingRemovals`, `restartCommand`,
 * `copied`) is kept here because the banner is meaningless without the
 * Paths handlers that produce it — splitting the two would force the
 * parent to hold this state purely to thread it back down.
 *
 * The banner renders ABOVE the section so it stays visible at the top of
 * the panel body. Parent passes nothing in; the section reads
 * `s.pending_path_changes` + `s.pending_library_removals` once at mount
 * to seed the banner.
 */
export function PathsSection({ s }: { s: AppSettings }) {
  const qc = useQueryClient()
  const [pendingPaths, setPendingPaths] = useState<Record<string, string>>(
    s.pending_path_changes ?? {},
  )
  const [pendingRemovals, setPendingRemovals] = useState<string[]>(
    s.pending_library_removals ?? [],
  )
  const [restartCommand, setRestartCommand] = useState('')
  const [copied, setCopied] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [addingLibrary, setAddingLibrary] = useState(false)
  const [newLibraryName, setNewLibraryName] = useState('')
  const [newLibraryPath, setNewLibraryPath] = useState('')

  // Re-seed if the parent's settings refresh underneath us.
  useEffect(() => {
    setPendingPaths(s.pending_path_changes ?? {})
    setPendingRemovals(s.pending_library_removals ?? [])
  }, [s.pending_path_changes, s.pending_library_removals])

  async function stagePath(mount: string, path: string) {
    const result = await api.stagePathChange(mount, path)
    setPendingPaths(result.pending)
    setRestartCommand(result.restart_command)
    qc.invalidateQueries({ queryKey: ['tree'] })
  }

  async function clearPending() {
    try {
      await api.clearPendingPaths()
      setPendingPaths({})
      setPendingRemovals([])
      setRestartCommand('')
      qc.invalidateQueries({ queryKey: ['app-settings'] })
      qc.invalidateQueries({ queryKey: ['tree'] })
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  async function removeLibrary(mount: string) {
    try {
      const result = await api.removeLibrary(mount)
      setPendingPaths(result.pending)
      setPendingRemovals(result.pending_removals)
      setRestartCommand(result.restart_command)
      qc.invalidateQueries({ queryKey: ['tree'] })
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  function copyCommand() {
    navigator.clipboard.writeText(restartCommand).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }

  async function addNewLibrary() {
    if (!newLibraryName || !newLibraryPath) {
      setError('Library name and path are required')
      return
    }
    try {
      await stagePath(newLibraryName, newLibraryPath)
      setNewLibraryName('')
      setNewLibraryPath('')
      setAddingLibrary(false)
    } catch (e) {
      setError(errorMessage(e))
    }
  }

  return (
    <>
      {/* Pending banner — rendered inline above the paths so it stays
          near the controls that produce it. */}
      {(Object.keys(pendingPaths).length > 0 || pendingRemovals.length > 0) && (
        <div className="sp-pending-banner">
          <div className="sp-pending-banner__icon">⚠️</div>
          <div className="sp-pending-banner__content">
            <div className="sp-pending-banner__title">
              Path changes pending — restart required
            </div>
            {pendingRemovals.length > 0 && (
              <div className="sp-pending-banner__subtitle">
                Libraries pending removal: {pendingRemovals.join(', ')}
              </div>
            )}
            {/* Which runtime, asked directly.
                This used to branch on `restartCommand` being empty, which
                answered the question by accident and got it wrong twice: the
                command is also empty under Docker until a stage happens in
                THIS session, so a Docker user returning to a pending change
                from a previous session was told to quit and reopen the app.
                `desktop_mode` comes from the backend, which is the only party
                that actually knows. */}
            {!s.desktop_mode ? (
              <>
                <div className="sp-pending-banner__subtitle">
                  Run this command in your terminal to apply changes:
                </div>
                <div className="sp-pending-banner__command">
                  <code>{restartCommand}</code>
                  <button
                    onClick={copyCommand}
                    className="sp-btn-copy"
                    title="Copy to clipboard"
                  >
                    {copied ? '✓ Copied' : 'Copy'}
                  </button>
                </div>
                <div className="sp-pending-banner__note">
                  After restarting containers, click "I've restarted" below to clear this message.
                </div>
              </>
            ) : (
              <div className="sp-pending-banner__note">
                Quit and reopen the app to apply these changes. This message
                clears itself once they have applied.
              </div>
            )}
            <div className="sp-pending-banner__actions">
              <button
                onClick={clearPending}
                className="sp-btn-secondary-sm"
              >
                I've restarted
              </button>
              <button
                onClick={clearPending}
                className="sp-btn-cancel-sm"
                title="Discard pending changes without restarting"
              >
                Cancel changes
              </button>
            </div>
          </div>
        </div>
      )}

      {error && <div className="sp-status-error" title={error}>Error: {error}</div>}

      <PathRow
        label="Library"
        currentPath={s.host_paths?.library ?? s.paths.library_root}
        mount="library"
        onStage={stagePath}
      />
      <PathRow
        label="Notes"
        currentPath={s.host_paths?.notes ?? s.paths.notes_path}
        mount="notes"
        onStage={stagePath}
      />
      <PathRow
        label="Generated"
        currentPath={s.host_paths?.generated ?? s.paths.generated_path}
        mount="generated"
        onStage={stagePath}
      />

      {/* Extra Libraries */}
      {s.extra_libraries && Object.keys(s.extra_libraries).length > 0 && (
        <>
          <div className="sp-section-divider" />
          <div className="sp-subsection-title">Extra Libraries</div>
          {Object.entries(s.extra_libraries)
            .filter(([name]) => !pendingRemovals.includes(name))
            .map(([name, path]) => (
              <PathRow
                key={name}
                label={name}
                currentPath={path}
                mount={name}
                onStage={stagePath}
                onRemove={() => removeLibrary(name)}
                isExtraLibrary
              />
            ))}
        </>
      )}

      {/* Add Library Button */}
      {!addingLibrary ? (
        <div className="sp-add-library-section">
          <button
            onClick={() => setAddingLibrary(true)}
            className="sp-btn-add-library"
          >
            + Add Library
          </button>
        </div>
      ) : (
        <div className="sp-add-library-form">
          <div className="sp-add-library-form__title">Add New Library</div>
          <div className="sp-add-library-form__fields">
            <div className="sp-add-library-field">
              <label className="sp-add-library-label">Mount Name</label>
              <input
                type="text"
                value={newLibraryName}
                onChange={(e) => setNewLibraryName(e.target.value)}
                placeholder="e.g., archive, books, papers"
                className="sp-add-library-input"
              />
              <span className="sp-add-library-hint">
                Alphanumeric, underscore, and hyphen only
              </span>
            </div>
            <div className="sp-add-library-field">
              <label className="sp-add-library-label">Host Path</label>
              <input
                type="text"
                value={newLibraryPath}
                onChange={(e) => setNewLibraryPath(e.target.value)}
                placeholder="/absolute/path/to/library"
                className="sp-add-library-input"
              />
            </div>
          </div>
          <div className="sp-add-library-actions">
            <button
              onClick={addNewLibrary}
              className="sp-btn-primary-sm"
            >
              Add Library
            </button>
            <button
              onClick={() => {
                setAddingLibrary(false)
                setNewLibraryName('')
                setNewLibraryPath('')
              }}
              className="sp-btn-cancel-sm"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </>
  )
}
