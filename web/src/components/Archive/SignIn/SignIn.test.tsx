import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { SignIn } from './SignIn'
import { SignOutButton } from './SignOutButton'
import { useSessionStore } from '../../../stores/sessionStore'

afterEach(() => { vi.unstubAllGlobals(); useSessionStore.setState({ name: null }) })

async function fill(name: string, pw: string) {
  const u = userEvent.setup()
  await u.type(screen.getByLabelText('Name'), name)
  await u.type(screen.getByLabelText('Password'), pw)
  await u.click(screen.getByRole('button', { name: 'Sign in' }))
}

describe('SignIn', () => {
  it('posts the name and password and reports the account', async () => {
    const f = vi.fn(async () => new Response(JSON.stringify({ name: 'ana', role: 'writer' }), { status: 200 }))
    vi.stubGlobal('fetch', f)
    const onSignedIn = vi.fn()
    render(<SignIn title="Local Archive" onSignedIn={onSignedIn} />)
    await fill('ana', 'pw-1')
    await waitFor(() => expect(onSignedIn).toHaveBeenCalledWith({ name: 'ana', role: 'writer' }))
    const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/archive/login')
    expect(JSON.parse(init.body as string)).toEqual({ name: 'ana', password: 'pw-1' })
  })

  it('a wrong password shows the error line and stays', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{"detail":"x"}', { status: 401 })))
    const onSignedIn = vi.fn()
    render(<SignIn title="Local Archive" onSignedIn={onSignedIn} />)
    await fill('ana', 'bad')
    await waitFor(() => expect(screen.getByRole('alert').textContent).toBe('Wrong name or password.'))
    expect(onSignedIn).not.toHaveBeenCalled()
  })

  it('a network failure says so rather than blaming the password', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('down') }))
    render(<SignIn title="Local Archive" onSignedIn={vi.fn()} />)
    await fill('ana', 'pw')
    await waitFor(() => expect(screen.getByRole('alert').textContent).toMatch(/Cannot reach the archive/))
  })

  it('empty fields are refused without a request', async () => {
    const f = vi.fn()
    vi.stubGlobal('fetch', f)
    render(<SignIn title="Local Archive" onSignedIn={vi.fn()} />)
    await userEvent.setup().click(screen.getByRole('button', { name: 'Sign in' }))
    expect(screen.getByRole('alert').textContent).toBe('Enter your name and password.')
    expect(f).not.toHaveBeenCalled()
  })
})

describe('SignOutButton', () => {
  it('is absent while nobody is signed in and present after', () => {
    const { rerender } = render(<SignOutButton />)
    expect(screen.queryByRole('button', { name: 'Sign out' })).toBeNull()
    useSessionStore.setState({ name: 'ana' })
    rerender(<SignOutButton />)
    expect(screen.getByRole('button', { name: 'Sign out' })).toBeDefined()
  })
})
