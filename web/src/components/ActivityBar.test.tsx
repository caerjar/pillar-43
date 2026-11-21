import { describe, it, expect, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ActivityBar } from './ActivityBar'
import { useSessionStore } from '../stores/sessionStore'
import { buildMenus, menuActions } from '../lib/menu/menuModel'
import { buildCommands } from './CommandPalette/commands'

afterEach(() => useSessionStore.setState({ name: null, role: null }))

const host = { openSearch() {}, openCommandPalette() {}, goBack() {}, goForward() {} }

describe('Settings is not offered to a writer', () => {
  it('the ribbon shows Settings to an admin', () => {
    useSessionStore.setState({ name: 'a', role: 'admin' })
    render(<ActivityBar />)
    expect(screen.getByRole('button', { name: 'Settings' })).toBeTruthy()
  })

  it('the ribbon hides Settings from a writer', () => {
    useSessionStore.setState({ name: 'w', role: 'writer' })
    render(<ActivityBar />)
    expect(screen.queryByRole('button', { name: 'Settings' })).toBeNull()
    expect(screen.getByRole('button', { name: 'My work' })).toBeTruthy()
  })

  it('the menu and palette drop Settings (and the ⌘, accelerator) when it is off', () => {
    const ids = (m: ReturnType<typeof buildMenus>) => menuActions(m).map((a) => a.id)
    expect(ids(buildMenus(host))).toContain('app.settings')
    const off = buildMenus({ ...host, canOpenSettings: false })
    expect(ids(off)).not.toContain('app.settings')
    expect(off.map((m) => m.label)).toEqual(['Go'])
    expect(buildCommands().some((c) => c.id === 'app.settings')).toBe(true)
    expect(buildCommands({ canOpenSettings: false }).some((c) => c.id === 'app.settings')).toBe(false)
  })
})
