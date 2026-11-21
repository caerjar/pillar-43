import { useState } from 'react'
import { Row } from './controls'
import { errorMessage } from '../../lib/errors'

export function PathRow({
  label,
  currentPath,
  mount,
  onStage,
  onRemove,
  isExtraLibrary,
}: {
  label: string
  currentPath: string
  mount: string
  onStage: (mount: string, path: string) => Promise<void>
  onRemove?: () => void
  isExtraLibrary?: boolean
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(currentPath)
  const [staging, setStaging] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function save() {
    if (draft === currentPath) {
      setEditing(false)
      return
    }

    setStaging(true)
    setError(null)
    try {
      await onStage(mount, draft)
      setEditing(false)
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setStaging(false)
    }
  }

  if (editing) {
    return (
      <Row label={label} description="Stage change, then restart with new path">
        <div className="sp-path-edit">
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            className="sp-path-input"
            placeholder="/absolute/path/to/folder"
          />
          <button
            onClick={save}
            disabled={staging}
            className="sp-btn-primary-sm"
          >
            {staging ? 'Staging…' : 'Stage'}
          </button>
          <button
            onClick={() => {
              setDraft(currentPath)
              setEditing(false)
              setError(null)
            }}
            className="sp-btn-cancel-sm"
          >
            Cancel
          </button>
        </div>
        {error && (
          <div className="sp-path-error">{error}</div>
        )}
      </Row>
    )
  }

  return (
    <Row
      label={label}
      description="Where this folder lives on your computer (set during install)"
      restartRequired
    >
      <div className="sp-path-display">
        <code className="sp-path-value" title={currentPath}>
          {currentPath}
        </code>
        <button
          onClick={() => setEditing(true)}
          className="sp-btn-ghost-sm"
        >
          Edit
        </button>
        {isExtraLibrary && onRemove && (
          <button
            onClick={onRemove}
            className="sp-btn-remove-sm"
            title="Remove this library"
          >
            Remove
          </button>
        )}
      </div>
    </Row>
  )
}
