import { useState, useEffect } from 'react'
import { useMutation } from '@tanstack/react-query'
import { api } from '../../../lib/api'
import { useToast } from '../../ui/Toast'

function MountIndicator({ label, ok, detail, optional }: {
  label: string
  ok: boolean
  detail?: string
  optional?: boolean
}) {
  return (
    <div className={`sp-mount-row${optional ? ' sp-mount-row--optional' : ''}`}>
      <span className={`sp-mount-status${ok ? ' sp-mount-status--ok' : ' sp-mount-status--bad'}`}>
        {ok ? '✓' : '✗'}
      </span>
      <span className="sp-mount-label">{label}</span>
      {detail && <span className="sp-mount-detail">{detail}</span>}
    </div>
  )
}

export function VaultHealthSection() {
  const [status, setStatus] = useState<Awaited<ReturnType<typeof api.libraryStatus>> | null>(null)
  useEffect(() => {
    api.libraryStatus().then(setStatus).catch(() => {})
  }, [])

  const { toast, error: toastError } = useToast()
  const { mutate: rebuildIndex, isPending } = useMutation({
    mutationFn: () => api.reindexBackground(false),
    onSuccess: () => {
      toast({ message: 'Re-indexing started — watch progress in the Maintain panel.', tone: 'success' })
    },
    onError: () => {
      toastError("Couldn't start re-indexing. Please try again.")
    },
  })

  return (
    <div className="sp-vault-health">
      <div className="sp-vault-health__hint">
        Live check of every mount and a one-click background re-index. Detailed maintenance
        and per-feature runs live in the Maintain panel.
      </div>
      {status ? (
        <>
          <MountIndicator
            label="notes/"
            ok={status.notes.exists && status.notes.writable}
            detail={
              !status.notes.exists ? 'missing'
              : !status.notes.writable ? 'not writable'
              : `read-write · ${status.notes.file_count} files`
            }
          />
          <MountIndicator
            label="library/"
            ok={status.library.exists}
            detail={status.library.exists ? `${status.library.file_count} files` : 'missing'}
            optional
          />
          <MountIndicator
            label="generated/"
            ok={status.generated.exists && status.generated.writable}
            detail={
              !status.generated.exists ? 'missing'
              : !status.generated.writable ? 'not writable'
              : `AI output · ${status.generated.file_count} files`
            }
          />
          {Object.entries(status.extra_libraries).map(([name, x]) => (
            <MountIndicator
              key={name}
              label={name}
              ok={x.exists}
              detail={x.exists ? `${x.file_count} files` : 'missing'}
              optional
            />
          ))}
        </>
      ) : (
        <div className="sp-mount-loading">Checking mounts…</div>
      )}
      <button
        className="sp-btn-primary-sm"
        disabled={isPending}
        onClick={() => rebuildIndex()}
      >
        {isPending ? 'Re-indexing…' : 'Re-index vault'}
      </button>
    </div>
  )
}
