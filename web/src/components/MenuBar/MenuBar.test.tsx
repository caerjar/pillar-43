/**
 * The in-app menu bar.
 *
 * Three things here are worth pinning, all of which fail silently rather than
 * loudly:
 *
 * 1. **It must not render in the native app.** The macOS shell builds a real
 *    menu from the same model; showing both means two menu bars saying the
 *    same thing, and the bug reads as a styling problem rather than a wiring
 *    one.
 * 2. **The opening click must not also close the menu.** Asserted as
 *    behaviour, not as a mechanism: an earlier version of this component
 *    deferred its listener attachment by a tick, copied from ContextMenu.tsx.
 *    Removing that deferral changed nothing here — ContextMenu opens from
 *    `onContextMenu` and needs it, this opens from `onClick` and does not — so
 *    the deferral was dropped rather than kept with a test that could not fail
 *    against its absence.
 * 3. **Every leaf must reach its `run`.** A menu whose items render but do
 *    nothing looks completely correct in a screenshot.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MenuBar, prettyAccelerator } from './MenuBar'
import type { MenuDef } from '../../lib/menu/menuModel'
import type { CommandCtx } from '../CommandPalette/commands'

const run = vi.fn()

const menus: MenuDef[] = [
  {
    id: 'go',
    label: 'Go',
    items: [
      { id: 'go.home', label: 'Home', chord: 'g h', run },
      'separator',
      { id: 'go.files', label: 'Files', chord: 'g f', run },
    ],
  },
  {
    id: 'view',
    label: 'View',
    items: [{ id: 'go.search', label: 'Search…', accelerator: 'CmdOrCtrl+K', run }],
  },
]

const ctx = {} as CommandCtx

beforeEach(() => vi.clearAllMocks())

describe('MenuBar', () => {
  it('does not render where a native menu exists', () => {
    render(<MenuBar menus={menus} ctx={ctx} hidden />)
    expect(screen.queryByRole('menubar')).not.toBeInTheDocument()
  })

  it('renders a title per menu', () => {
    render(<MenuBar menus={menus} ctx={ctx} />)
    expect(screen.getByRole('button', { name: 'Go' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'View' })).toBeInTheDocument()
  })

  it('opens on click and stays open', async () => {
    // Behavioural, not mechanistic. A menu that closes itself on the click
    // that opened it looks exactly like a menu that does not open — no error,
    // nothing in the console — so it is worth asserting even though the
    // current implementation cannot produce it.
    render(<MenuBar menus={menus} ctx={ctx} />)
    await userEvent.click(screen.getByRole('button', { name: 'Go' }))
    expect(await screen.findByRole('menu', { name: 'Go' })).toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: /Home/ })).toBeInTheDocument()
  })

  it('runs the action and closes', async () => {
    render(<MenuBar menus={menus} ctx={ctx} />)
    await userEvent.click(screen.getByRole('button', { name: 'Go' }))
    await userEvent.click(await screen.findByRole('menuitem', { name: /Files/ }))

    expect(run).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })

  it('closes on Escape', async () => {
    render(<MenuBar menus={menus} ctx={ctx} />)
    await userEvent.click(screen.getByRole('button', { name: 'Go' }))
    await screen.findByRole('menu', { name: 'Go' })

    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })

  it('closes when clicking outside', async () => {
    render(
      <div>
        <MenuBar menus={menus} ctx={ctx} />
        <button type="button">elsewhere</button>
      </div>,
    )
    await userEvent.click(screen.getByRole('button', { name: 'Go' }))
    await screen.findByRole('menu', { name: 'Go' })

    await userEvent.click(screen.getByRole('button', { name: 'elsewhere' }))
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })

  it('switches menus on hover once one is open', async () => {
    // Standard menu-bar behaviour. Without it, browsing the menus costs two
    // clicks each.
    render(<MenuBar menus={menus} ctx={ctx} />)
    await userEvent.click(screen.getByRole('button', { name: 'Go' }))
    await userEvent.hover(screen.getByRole('button', { name: 'View' }))

    expect(await screen.findByRole('menu', { name: 'View' })).toBeInTheDocument()
    expect(screen.queryByRole('menu', { name: 'Go' })).not.toBeInTheDocument()
  })

  it('does not open on hover when nothing is open yet', async () => {
    render(<MenuBar menus={menus} ctx={ctx} />)
    await userEvent.hover(screen.getByRole('button', { name: 'Go' }))
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })

  it('shows the chord for panel destinations', async () => {
    render(<MenuBar menus={menus} ctx={ctx} />)
    await userEvent.click(screen.getByRole('button', { name: 'Go' }))
    expect(await screen.findByText('g f')).toBeInTheDocument()
  })
})

describe('prettyAccelerator', () => {
  it('renders Tauri spelling as Mac symbols', () => {
    // The model stores Tauri's form because the native menu needs it; only the
    // in-app renderer has to make it look like a shortcut.
    expect(prettyAccelerator('CmdOrCtrl+K')).toBe('⌘K')
    expect(prettyAccelerator('CmdOrCtrl+Shift+F')).toBe('⌘⇧F')
    expect(prettyAccelerator('CmdOrCtrl+[')).toBe('⌘[')
  })
})
