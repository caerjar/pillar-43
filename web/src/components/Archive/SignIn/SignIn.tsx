/**
 * Sign-in for the organization profile. Shown when GET /api/archive/me
 * answers 401. A name, a password, one button, and an error line.
 */
import { useRef, useState } from 'react'
import { Button } from '../Button'
import { signIn } from '../../../lib/api/archive'

interface Props {
  title: string
  onSignedIn: (account: { name: string; role: string }) => void
}

const field: React.CSSProperties = {
  minHeight: 32,
  padding: '0 var(--space-3)',
  background: 'var(--bg-panel)',
  color: 'var(--text-primary)',
  border: '1px solid var(--border)',
  borderRadius: 'var(--radius-md)',
  fontSize: 'var(--text-sm)',
  fontFamily: 'inherit',
}
const label: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 'var(--space-1)',
  fontSize: 'var(--text-xs)',
  color: 'var(--text-secondary)',
}

export function SignIn({ title, onSignedIn }: Props) {
  const [name, setName] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const nameRef = useRef<HTMLInputElement>(null)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    if (busy) return
    if (!name.trim() || !password) {
      setError('Enter your name and password.')
      return
    }
    setBusy(true)
    setError('')
    try {
      onSignedIn(await signIn(name.trim(), password))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Sign-in failed.')
      setPassword('')
      nameRef.current?.focus()
    } finally {
      setBusy(false)
    }
  }

  return (
    <main
      data-testid="sign-in"
      style={{ position: 'fixed', inset: 0, background: 'var(--bg-base)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 'var(--space-4)' }}
    >
      <form
        onSubmit={submit}
        aria-label="Sign in"
        style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)', width: '100%', maxWidth: 320 }}
      >
        <h1 style={{ margin: 0, fontSize: 'var(--text-md)', fontWeight: 'var(--weight-medium)', color: 'var(--text-primary)' }}>{title}</h1>
        <label style={label}>
          Name
          <input ref={nameRef} style={field} value={name} onChange={(e) => setName(e.target.value)} autoComplete="username" autoFocus />
        </label>
        <label style={label}>
          Password
          <input style={field} type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
        </label>
        <Button type="submit" variant="primary" disabled={busy}>Sign in</Button>
        <p role="alert" style={{ margin: 0, minHeight: '1.5em', fontSize: 'var(--text-xs)', color: 'var(--error)' }}>{error}</p>
      </form>
    </main>
  )
}
