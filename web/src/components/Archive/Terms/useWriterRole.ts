/**
 * Whether the signed-in account is a writer. The ribbon shows "My work" to
 * writers only; the backend refuses everyone else the data regardless.
 * A writer has no Ask view (it answers 403), so they land on My work.
 */
import { useEffect } from 'react'
import { fetchSession } from '../../../lib/api/archive'
import { useAppStore } from '../../../stores/appStore'
import { useSessionStore } from '../../../stores/sessionStore'

export function useWriterRole(): boolean {
  const name = useSessionStore((s) => s.name)
  const role = useSessionStore((s) => s.role)
  const setRole = useSessionStore((s) => s.setRole)
  const leftTab = useAppStore((s) => s.leftTab)
  const setLeftTab = useAppStore((s) => s.setLeftTab)

  useEffect(() => {
    if (!name || role) return
    void fetchSession().then((s) => { if (s.state === 'signed-in') setRole(s.role) })
  }, [name, role, setRole])

  const isWriter = role === 'writer'
  useEffect(() => {
    if (isWriter && leftTab !== 'terms') setLeftTab('terms')
  }, [isWriter, leftTab, setLeftTab])
  return isWriter
}
