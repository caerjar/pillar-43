import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from './App'
import { useAppStore } from './stores/appStore'
import { api } from './lib/api'

vi.mock('./lib/api', () => ({
  api: {
    tree: vi.fn().mockResolvedValue([]),
    treeDir: vi.fn().mockResolvedValue([]),
    readFile: vi.fn().mockRejectedValue(new Error('not found')),
    writeFile: vi.fn().mockResolvedValue({ ok: true }),
    search: vi.fn().mockResolvedValue({ results: [] }),
    opacityMap: vi.fn().mockResolvedValue({ entries: {} }),
    catalogStats: vi.fn().mockResolvedValue({
      file_count: 10, catalog_count: 10, embedding_count: 10, last_indexed_at: null, interrupted: false,
    }),
    libraryStatus: vi.fn().mockResolvedValue({
      setup_complete: true,
      notes: { exists: true, writable: true, git_ready: true, file_count: 10 },
      generated: { exists: true, writable: true, file_count: 5 },
      library: { exists: false, file_count: 0 },
    }),
    appSettings: vi.fn().mockResolvedValue({
      library_readonly: true,
      move_confirm: 'confirm',
      voice_language: '',
      paths: { library_root: '/library', notes_path: '/notes', generated_path: '/generated' },
    }),
  },
}))

const PROFILE = {
  title: 'Local Archive', org_name: 'Lantern Wharf Editions', nav: ['ask', 'files', 'settings'], answer_model: 'local',
}

function stubProfile(impl: () => Promise<unknown>) {
  vi.stubGlobal('fetch', vi.fn(impl))
}

// The shell asks the backend for the press's profile; answer it for every test.
beforeEach(() => {
  stubProfile(async () => new Response(JSON.stringify(PROFILE), { status: 200 }))
})
afterEach(() => { vi.unstubAllGlobals() })

describe('App layout', () => {
  beforeEach(() => {
    // Reset Zustand singleton state between tests
    useAppStore.setState({
      currentFile: null,
      leftTab: 'files',
      panelMode: 'normal',
    })
  })

  it('renders the app root', async () => {
    render(<App />)
    expect(await screen.findByTestId('app')).toBeDefined()
  })

  it('shows Ask and Settings, and none of the removed panels', async () => {
    render(<App />)
    await screen.findByTestId('ask-view')
    expect(screen.getByLabelText('Ask')).toBeDefined()
    // The names are written on the ribbon, not only in a hover tooltip.
    expect(screen.getByLabelText('Ask').textContent).toContain('Ask')
    expect(screen.getByLabelText('Settings')).toBeDefined()
    // Files is for an admin alone.
    expect(screen.queryByLabelText('Files')).toBeNull()
    for (const hidden of ['Threads', 'Tasks', 'Home', 'Open AI sidebar', 'Close AI sidebar']) {
      expect(screen.queryByLabelText(hidden), hidden).toBeNull()
    }
    expect(screen.queryByTestId('new-note-btn')).toBeNull()
    expect(screen.queryByTestId('ai-input')).toBeNull()
    expect(screen.queryByTestId('home')).toBeNull()
  })

  it('names the press in the top bar and the window title', async () => {
    render(<App />)
    await screen.findByTestId('app')
    expect(screen.getByText('Local Archive')).toBeDefined()
    expect(screen.queryByText('pillar43')).toBeNull()
    expect(document.title).toBe('Local Archive')
  })

  it('a profile fetch failure keeps the default title and the same shell', async () => {
    stubProfile(async () => { throw new TypeError('network down') })
    render(<App />)
    await screen.findByTestId('app')
    expect(screen.getByLabelText('Ask')).toBeDefined()
  })

  it('opens the help overlay naming what exists', async () => {
    const user = userEvent.setup()
    render(<App />)
    await screen.findByTestId('app')
    await user.click(screen.getByTestId('help-btn'))
    const dialog = await screen.findByRole('dialog')
    for (const name of ['Ask', 'Explore', 'People', 'My work', 'Files']) {
      expect(dialog.textContent, name).toContain(name)
    }
    expect(dialog.textContent).not.toMatch(/Claude|Maintain|Inbox|Tasks|Commons|Pillar-43/)
  })

  it('shows the Ask view in the center when no file is open', async () => {
    render(<App />)
    await screen.findByTestId('app')
    expect(await screen.findByTestId('ask-view')).toBeDefined()
  })

  it('shows search button', async () => {
    render(<App />)
    await screen.findByTestId('app')
    expect(screen.getByTestId('search-btn')).toBeDefined()
  })

  it('opens search palette on search button click', async () => {
    const user = userEvent.setup()
    render(<App />)
    await screen.findByTestId('app')
    await user.click(screen.getByTestId('search-btn'))
    expect(await screen.findByTestId('search-palette')).toBeDefined()
  })

  it('shows theme toggle button', async () => {
    render(<App />)
    await screen.findByTestId('app')
    expect(screen.getByTestId('theme-btn')).toBeDefined()
  })

})

// ── Startup gating ───────────────────────────────────────────────────────────
//
// A persistent API failure never opens the shell: the user stays on the
// "Starting …" splash and, after a threshold, gets a "Taking longer
// than usual" affordance with a Retry button.
describe('AppShell startup gating', () => {
  beforeEach(() => {
    useAppStore.setState({
      currentFile: null,
      leftTab: 'files',
      panelMode: 'normal',
    })
    vi.mocked(api.libraryStatus).mockReset()
    // Restore the default happy-path mock so any test that doesn't override
    // it gets the same shape as the rest of the suite.
    vi.mocked(api.libraryStatus).mockResolvedValue({
      setup_complete: true,
      notes: { exists: true, writable: true, git_ready: true, file_count: 10 },
      generated: { exists: true, writable: true, file_count: 5 },
      library: { exists: false, file_count: 0 },
    } as any)
  })

  it('opens the shell when libraryStatus is initially slow then succeeds', async () => {
    // Reject 3 times, then resolve with git_ready: true.
    // Retry delays: ~250ms + 375ms + 562ms ≈ 1.2s before the success.
    vi.mocked(api.libraryStatus)
      .mockRejectedValueOnce(new Error('connection refused'))
      .mockRejectedValueOnce(new Error('connection refused'))
      .mockRejectedValueOnce(new Error('connection refused'))
      .mockResolvedValue({
        setup_complete: true,
        notes: { exists: true, writable: true, git_ready: true, file_count: 10 },
        generated: { exists: true, writable: true, file_count: 5 },
        library: { exists: false, file_count: 0 },
      } as any)

    render(<App />)
    // Eventually we render the real app.
    await waitFor(
      () => expect(screen.getByTestId('app')).toBeDefined(),
      { timeout: 5000 },
    )
  })

  it('shows slow-start affordance after threshold and never the shell', async () => {
    vi.mocked(api.libraryStatus).mockRejectedValue(new Error('connection refused'))

    render(<App />)
    // Splash is up immediately.
    expect(await screen.findByText('Starting Local Archive…')).toBeDefined()
    // After ~3s the slow-start hint appears. Bound at 6s real-time to leave
    // headroom for the retry backoff (250ms * 1.5^N) crossing the threshold.
    await waitFor(
      () => expect(screen.getByText(/Taking longer than usual/)).toBeDefined(),
      { timeout: 6000 },
    )
    expect(screen.getByRole('button', { name: /Retry now/i })).toBeDefined()
    // Even with the API persistently failing, the shell never opens.
    expect(screen.queryByTestId('app')).toBeNull()
  }, 8000)
})

/**
 * The `g`-chords the menu and ribbon advertise.
 *
 * These shipped displayed-but-unbound for exactly one commit, which is the
 * worst state for a shortcut: the UI teaches it, the key does nothing, and
 * nothing errors. The bindings are now derived from the menu model rather than
 * a list written in App.tsx, so what is shown and what fires cannot diverge —
 * and this is the test that says so behaviourally rather than structurally.
 */
describe('App — panel chords', () => {
  beforeEach(() => {
    // The startup-gating block above leaves libraryStatus rejecting, which
    // parks the app on its splash forever. Restore a healthy vault first.
    vi.mocked(api.libraryStatus).mockResolvedValue({
      setup_complete: true,
      notes: { exists: true, writable: true, git_ready: true, file_count: 10 },
      generated: { exists: true, writable: true, file_count: 5 },
      library: { exists: false, file_count: 0 },
    } as Awaited<ReturnType<typeof api.libraryStatus>>)
    useAppStore.setState({
      currentFile: null,
      leftTab: 'files',
      panelMode: 'normal',
    })
  })

  it('a lone g does nothing', async () => {
    // The chord prefix must not be an action on its own, or every `g` typed
    // outside a text field would navigate.
    render(<App />)
    await screen.findByTestId('app')

    await userEvent.keyboard('g')
    expect(useAppStore.getState().leftTab).toBe('ask')
  })

  it('g f goes to Files and g a back to Ask', async () => {
    render(<App />)
    await screen.findByTestId('app')

    await userEvent.keyboard('gf')
    await waitFor(() => expect(useAppStore.getState().leftTab).toBe('files'))
    await userEvent.keyboard('ga')
    await waitFor(() => expect(useAppStore.getState().leftTab).toBe('ask'))
  })
})

/**
 * The ⌘-shortcuts the menus advertise.
 *
 * ⌘, was reported dead from the built app: it was in the Pillar-43 menu and in
 * the model, and nothing in the page handled it — so it depended entirely on
 * the native menu binding, and did nothing in the browser build at all. These
 * assert the page's own handling, which is what makes the two runtimes agree.
 */
describe('App — menu accelerators', () => {
  beforeEach(() => {
    vi.mocked(api.libraryStatus).mockResolvedValue({
      setup_complete: true,
      notes: { exists: true, writable: true, git_ready: true, file_count: 10 },
      generated: { exists: true, writable: true, file_count: 5 },
      library: { exists: false, file_count: 0 },
    } as Awaited<ReturnType<typeof api.libraryStatus>>)
    useAppStore.setState({
      currentFile: null,
      leftTab: 'files',
      panelMode: 'normal',
    })
  })

  it('⌘, opens Settings', async () => {
    render(<App />)
    await screen.findByTestId('app')

    await userEvent.keyboard('{Meta>},{/Meta}')
    // Settings is a Preferences window, not a tab — assert the window opened
    // and that the rail was left alone, which is the whole point of the change.
    await waitFor(() => expect(useAppStore.getState().settingsOpen).toBe(true))
    expect(useAppStore.getState().leftTab).toBe('ask')
  })

  it('⌘⇧F toggles focus mode', async () => {
    render(<App />)
    await screen.findByTestId('app')

    await userEvent.keyboard('{Meta>}{Shift>}F{/Shift}{/Meta}')
    await waitFor(() => expect(useAppStore.getState().panelMode).toBe('focus'))
  })
})

describe('App — sign-in and admin', () => {
  // App holds a module-level QueryClient that caches the profile for an hour,
  // so each test loads a fresh copy of the modules (and of the stores with them).
  async function load() {
    vi.resetModules()
    const { default: Fresh } = await import('./App')
    const { useAppStore: store } = await import('./stores/appStore')
    store.setState({ currentFile: null, leftTab: 'files', panelMode: 'normal' })
    return { Fresh, store }
  }

  it('an admin has Files one click away and it opens the tree beside the Ask view', async () => {
    const { Fresh, store } = await load()
    const { useSessionStore } = await import('./stores/sessionStore')
    useSessionStore.setState({ name: 'probe-admin', role: 'admin' })
    render(<Fresh />)
    await screen.findByTestId('ask-view')
    expect(screen.getByLabelText('Files')).toBeDefined()
    store.getState().setLeftTab('files')
    await waitFor(() => expect(document.querySelector('.left-panel')).not.toBeNull())
  })

  it('library status 401 and /me 401 shows the sign-in screen', async () => {
    stubProfile(async (...a: unknown[]) => {
      const url = String(a[0])
      if (url.includes('/api/archive/me')) return new Response('{"detail":"Sign in"}', { status: 401 })
      return new Response(JSON.stringify(PROFILE), { status: 200 })
    })
    const { Fresh } = await load()
    const { api: freshApi } = await import('./lib/api')
    vi.mocked(freshApi.libraryStatus).mockRejectedValueOnce(new Error('401 Unauthorized: {"detail":"Sign in"}'))
    render(<Fresh />)
    expect(await screen.findByRole('button', { name: 'Sign in' })).toBeDefined()
    expect(screen.getByLabelText('Name')).toBeDefined()
    expect(screen.getByLabelText('Password')).toBeDefined()
  })

  it('a 401 while /me is unreachable stays on the splash, never sign-in', async () => {
    stubProfile(async (...a: unknown[]) => {
      const url = String(a[0])
      if (url.includes('/api/archive/me')) throw new TypeError('network down')
      return new Response(JSON.stringify(PROFILE), { status: 200 })
    })
    const { Fresh } = await load()
    const { api: freshApi } = await import('./lib/api')
    vi.mocked(freshApi.libraryStatus).mockRejectedValueOnce(new Error('401 Unauthorized: x'))
    render(<Fresh />)
    await screen.findByTestId('ask-view') // the retry succeeded; sign-in was never shown
    expect(screen.queryByRole('button', { name: 'Sign in' })).toBeNull()
  })
})
