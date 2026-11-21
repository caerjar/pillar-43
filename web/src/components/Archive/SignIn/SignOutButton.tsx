/** "Sign out" in the org ribbon. Visible only while an account is signed in. */
import { LogOut } from 'lucide-react'
import { signOut } from '../../../lib/api/archive'
import { useSessionStore } from '../../../stores/sessionStore'

export function SignOutButton() {
  const name = useSessionStore((s) => s.name)
  if (!name) return null
  return (
    <button
      type="button"
      aria-label="Sign out"
      title={`Sign out ${name}`}
      onClick={async () => {
        try {
          await signOut()
        } finally {
          // Reload drops every cached answer from the signed-out account.
          window.location.reload()
        }
      }}
      style={{ width: 60, height: 48, display: 'flex', flexDirection: 'column', gap: 2, alignItems: 'center', justifyContent: 'center', background: 'transparent', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', flexShrink: 0, fontFamily: 'inherit', fontSize: 'var(--text-xs)' }}
    >
      <LogOut size={16} strokeWidth={1.75} />
      <span style={{ whiteSpace: 'nowrap' }}>Sign out</span>
    </button>
  )
}
