import { lazy, Suspense, useState, useEffect, useCallback, useMemo, useRef } from 'react'
import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from '@tanstack/react-query'
import { AnimatePresence, motion } from 'framer-motion'
import { useAppStore } from './stores/appStore'
import { useGlobalKeyboard } from './hooks/useGlobalKeyboard'
import { useStructuredErrorAlert } from './hooks/useStructuredErrorAlert'
import { FileTree } from './components/FileTree/FileTree'
import { Editor } from './components/Editor/Editor'
import { SearchPalette } from './components/Search/SearchPalette'
import { CommandPalette } from './components/CommandPalette/CommandPalette'
import { MenuBar } from './components/MenuBar/MenuBar'
import { buildMenus } from './lib/menu/menuModel'
import { ExploreView } from './components/Archive/Explore/ExploreView'
import { BackToView } from './components/Archive/openFile'
import { PeopleView } from './components/Archive/People/PeopleView'
import { useProfileStore, DEFAULT_TITLE } from './stores/profileStore'
import { fetchArchiveProfile } from './lib/api/archive'
import { AskPage } from './components/Archive/Ask/AskPage'
import { TermsView } from './components/Archive/Terms/TermsView'
import { useCommandCtx } from './lib/menu/useCommandCtx'
import { menuActions, acceleratorToCombo } from './lib/menu/menuModel'
import { onNativeMenu } from './lib/desktop'
import { JobStatusBar } from './components/ui/JobStatusBar'
import { ActivityBar } from './components/ActivityBar'
import { ResizeHandle } from './components/ui/ResizeHandle'
import { api } from './lib/api'
import { ConfirmProvider } from './components/ui/Confirm'
import { PromptProvider } from './components/ui/Prompt'
import { ConfirmDestructiveProvider } from './components/ui/ConfirmDestructive'
import { ToastProvider } from './components/ui/Toast'
import './index.css'
import { STALE_TIME } from './constants'
import { clickable } from './lib/a11y'
import { SignIn } from './components/Archive/SignIn/SignIn'
import { fetchSession } from './lib/api/archive'
import { useSessionStore } from './stores/sessionStore'

// ── Lazy-loaded panels ────────────────────────────────────────────────────────
const SettingsWindow     = lazy(() => import('./components/Settings/SettingsWindow').then(m => ({ default: m.SettingsWindow })))

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: STALE_TIME.DEFAULT,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
})

function Layout() {
  const {
    leftTab, setLeftTab,
    panelMode, toggleFocusMode,
    goBack, goForward,
    currentFile, setCurrentFile,
    lightMode, setLightMode,
  } = useAppStore()

  const isFocus = panelMode === 'focus'
  const title = useProfileStore((s) => s.title)
  const isAdminSession = useSessionStore((s) => s.role === 'admin')
  const isWriterSession = useSessionStore((s) => s.role === 'writer')
  const [showSearch, setShowSearch] = useState(false)
  const [showCommandPalette, setShowCommandPalette] = useState(false)
  const [leftWidth, setLeftWidth] = useState(() =>
    parseInt(localStorage.getItem('pillar43.leftPanelWidth') ?? '280', 10)
  )
  const [showHelp, setShowHelp] = useState(false)

  const handleLeftResize = useCallback((w: number) => {
    setLeftWidth(w)
    localStorage.setItem('pillar43.leftPanelWidth', String(w))
  }, [])

  // ── Menus ──────────────────────────────────────────────────────────────────
  // One model, rendered by the in-app bar here and by the native macOS menu in
  // the Tauri shell. `desktop_mode` decides which; it is reported by the
  // backend rather than sniffed, same as everywhere else.
  const commandCtx = useCommandCtx()

  const menus = useMemo(
    () => buildMenus({
      openSearch: () => setShowSearch((v) => !v),
      openCommandPalette: () => setShowCommandPalette((v) => !v),
      goBack,
      goForward,
      canOpenSettings: !isWriterSession,
    }),
    [goBack, goForward, isWriterSession],
  )

  // The native macOS menu dispatches an item id; run the same action the
  // in-app bar would. No-op in the browser, where the event never fires.
  useEffect(() => {
    const actions = menuActions(menus)
    return onNativeMenu((id) => {
      const hit = actions.find((a) => a.id === id)
      if (hit) void hit.run(commandCtx)
    })
  }, [menus, commandCtx])

  // On page load, start with no file open.
  useEffect(() => {
    setCurrentFile(null)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // Structured-error toast for any backend call that reports a classified
  // error_code (billing_exhausted, authentication_error, model_not_found,
  // rate_limit, provider_connection). Single mount point — the SSE consumers
  // write to lastError; this hook is the only listener.
  useStructuredErrorAlert()

  const { data: appSettings } = useQuery({
    queryKey: ['app-settings'],
    queryFn: () => api.appSettings(),
    staleTime: STALE_TIME.DEFAULT,
  })

  // Which menu surface is real. Reported by the backend rather than sniffed —
  // same rule as everywhere else that asks this question.
  const desktopMode = appSettings?.desktop_mode === true

  // Escape only. Every ⌘-shortcut moved into the model-derived bindings below
  // — they were listed here AND advertised in the menu, which meant ⌘N and ⌘,
  // appeared in both menus while being bound in neither, and the rest were
  // true in two places at once.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setShowSearch(false)
        setShowCommandPalette(false)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  // Day 2 polish — plain-letter bindings (text-input-gated via useGlobalKeyboard).
  // The inline handler above covers all modifier-shortcut bindings; this adds
  // the bare-letter ones that must NOT fire while typing in the editor or
  // a palette. The hook reads isTextInput on every keydown.
  //
  // The `g`-chords come from the menu model rather than a list written here,
  // so what the menu and ribbon ADVERTISE and what is actually BOUND cannot
  // drift apart. They were displayed before they were bound for exactly one
  // commit, and an advertised-but-dead shortcut is worse than none.
  const keyBindings = useMemo(() => {
    const bindings: Record<string, (e: KeyboardEvent) => void> = {
      '/': (e) => { e.preventDefault(); setShowSearch(true) },
      '?': (e) => { e.preventDefault(); setShowHelp(true) },
      // ⌘⇧F is bound here rather than derived from the menu model, because
      // there is no longer a View menu to derive it from — see the block
      // comment where that menu used to be in `lib/menu/menuModel.ts`. Focus
      // mode keeps its top-bar button and its command-palette entry; this is
      // the third surface, and without it the shortcut would have vanished
      // along with the menu title. Paired with that comment: if View ever
      // comes back, this line goes, or ⌘⇧F ends up bound twice.
      'mod+shift+f': (e) => { e.preventDefault(); toggleFocusMode() },
    }
    for (const action of menuActions(menus)) {
      const run = (e: KeyboardEvent) => { e.preventDefault(); void action.run(commandCtx) }
      if (action.chord) bindings[action.chord] = run
      // Accelerators too: the native menu binds these on macOS, but the
      // browser build has no menu to bind them, so the page must.
      if (action.accelerator) bindings[acceleratorToCombo(action.accelerator)] = run
    }
    // ⌘O is a second, undisplayed route to the palette, kept from the original
    // handler for muscle memory. Not in the model — a menu showing two
    // shortcuts for one item is noise.
    bindings['mod+o'] = bindings['mod+p']
    return bindings
  }, [menus, commandCtx, toggleFocusMode])

  useGlobalKeyboard(keyBindings)

  // Land on Ask.
  useEffect(() => {
    setLeftTab('ask')
  }, [setLeftTab])

  // Light / dark via data-theme on :root
  useEffect(() => {
    document.documentElement.dataset.theme = lightMode ? 'light' : ''
  }, [lightMode])

  return (
    <div
      style={{ display: 'flex', flexDirection: 'column', height: '100vh', background: 'var(--bg-base)' }}
      data-testid="app"
    >

      {/* Focus mode escape hatch */}
      {isFocus && (
        <button
          onClick={toggleFocusMode}
          title="Exit focus mode (⌘⇧F)"
          style={{
            position: 'fixed', top: 10, right: 14, zIndex: 1000,
            background: 'var(--bg-panel)',
            border: '1px solid var(--border)',
            borderRadius: 4,
            color: 'var(--text-muted)',
            fontSize: 11,
            padding: '3px 10px',
            cursor: 'pointer',
          }}
        >
          ⊠ exit focus
        </button>
      )}

      {/* Top bar */}
      {!isFocus && <div className="topbar">
        <span className="topbar__wordmark">{title}</span>

        {/* Renders only where there is no native menu. In the macOS app the
            Tauri shell builds a real one from the same model, and two menu
            bars saying the same thing is worse than either alone. */}
        <MenuBar menus={menus} ctx={commandCtx} hidden={desktopMode} />

        <div style={{ flex: 1 }} />

        {/* Search */}
        <button
          onClick={() => setShowSearch(true)}
          data-testid="search-btn"
          aria-label="Search"
          className="topbar__search"
        >
          <span className="topbar__search-icon">⌕</span>
          <span className="topbar__search-label">Search</span>
          <kbd className="topbar__search-kbd">⌘K</kbd>
        </button>

        <div className="topbar__divider" />

        <button
          onClick={() => setShowHelp(true)}
          data-testid="help-btn"
          title="Help (?)"
          aria-label="Help"
          className="btn btn-ghost btn--icon"
          style={{ fontSize: 14 }}
        >
          ?
        </button>

        {/* Theme */}
        <button
          onClick={() => setLightMode(!lightMode)}
          data-testid="theme-btn"
          title={lightMode ? 'Switch to dark mode' : 'Switch to light mode'}
          aria-label={lightMode ? 'Switch to dark mode' : 'Switch to light mode'}
          className="btn btn-ghost btn--icon"
          style={{ fontSize: 14 }}
        >
          {lightMode ? '☾' : '☀'}
        </button>
      </div>}

      {/* Body — [ActivityBar | LeftPanel | Editor | AISidebar] */}
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>

        {/* Activity bar — hidden in focus mode */}
        {!isFocus && <ActivityBar />}

        {/* Left panel — the file tree, for an admin; every other view fills the centre */}
        <AnimatePresence>
          {!isFocus && leftTab === 'files' && isAdminSession && (
            <motion.div
              key="left-panel"
              className="left-panel"
              initial={{ width: 0, opacity: 0 }}
              animate={{ width: leftWidth, opacity: 1 }}
              exit={{ width: 0, opacity: 0 }}
              transition={{ duration: 0.2 }}
              style={{
                borderRight: '1px solid var(--border)',
                display: 'flex',
                flexDirection: 'column',
                background: 'var(--bg-panel)',
                flexShrink: 0,
                overflow: 'hidden',
                position: 'relative',
              }}
            >
              {/* Panel content — zoom-depth transition (Eames: zooming in, not tab-switching) */}
              <AnimatePresence mode="wait">
                <motion.div
                  key={leftTab}
                  initial={{ opacity: 0, scale: 0.98 }}
                  animate={{ opacity: 1, scale: 1 }}
                  exit={{ opacity: 0, scale: 1.01 }}
                  transition={{ duration: 0.12, ease: [0.0, 0.0, 0.2, 1.0] }}
                  style={{ display: 'flex', flexDirection: 'column', flex: 1, overflow: 'hidden' }}
                >
                  {leftTab === 'files' && <FileTree />}
                </motion.div>
              </AnimatePresence>

              {/* Left panel resize handle */}
              <ResizeHandle onResize={handleLeftResize} minWidth={220} maxWidth={900} />
            </motion.div>
          )}
        </AnimatePresence>

        {/* Center — the archive views, or the file the admin opened. Settings is
            a window (SettingsWindow, rendered above the shell), not a centre pane. */}
        <div
          style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', background: 'var(--bg-base)' }}
        >
          {leftTab === 'files' && currentFile && <BackToView />}
          {leftTab === 'terms' ? (
            <TermsView />
          ) : leftTab === 'explore' ? (
            <ExploreView />
          ) : leftTab === 'people' ? (
            <PeopleView />
          ) : leftTab === 'ask' || !currentFile ? (
            <AskPage />
          ) : (
            <Editor />
          )}
        </div>
      </div>

      {/* Job status bar */}
      <JobStatusBar />

      {/* Preferences (⌘, / Pillar-43 → Settings…). Mounted here rather than in
          the centre pane so it floats over whatever you were doing. It reads
          `settingsOpen` itself and renders null when closed, so the lazy chunk
          is only fetched once the user actually opens it. */}
      <Suspense fallback={null}>
        <SettingsWindow />
      </Suspense>

      {/* Search Palette */}
      {showSearch && <SearchPalette onClose={() => setShowSearch(false)} />}
      {showCommandPalette && <CommandPalette onClose={() => setShowCommandPalette(false)} />}

      {/* Help overlay */}
      {showHelp && (
        <div
          {...clickable(() => setShowHelp(false))}
          role="dialog"
          aria-modal="true"
          aria-label={`${title} help`}
          style={{
            position: 'fixed', inset: 0, zIndex: 900,
            background: 'rgba(0,0,0,0.55)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            padding: 24,
          }}
        >
          <div {...clickable((e) => e.stopPropagation())} style={{
            background: 'var(--bg-panel)', border: '1px solid var(--border)',
            borderRadius: 12, padding: '32px 36px', maxWidth: 560, width: '100%',
            maxHeight: '80vh', overflowY: 'auto',
            boxShadow: '0 8px 32px rgba(0,0,0,0.28)',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
              <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--text-primary)' }}>{title}</div>
              <button
                onClick={() => setShowHelp(false)}
                aria-label="Close help"
                style={{ background: 'none', border: 'none', color: 'var(--text-muted)', fontSize: 20, cursor: 'pointer', lineHeight: 1 }}
              >×</button>
            </div>

            {[
              { title: 'Ask', desc: 'Ask a question in plain words. The answer cites the documents it came from, quotes them, and says what the archive does not hold. Items closed to the model are not read.' },
              { title: 'Explore', desc: 'Look across the whole archive: search by meaning, and see what a query finds and what it leaves out.' },
              { title: 'People', desc: 'The writers, translators and editors named in the archive, with the items that mention each.' },
              { title: 'My work', desc: 'For writers: your own items and the terms on them. Set who may read each one.' },
              { title: 'Files', desc: 'The archive folders and their documents, for admins. Open one to read it.' },
              { title: 'Search (⌘K)', desc: 'Jump to a file by name or by what it says.' },
              { title: 'Settings (⌘,)', desc: 'The local model and where the archive is stored. Accounts are made with the command line, not here.' },
            ].map(({ title: t, desc }) => (
              <div key={t} style={{ padding: '10px 0', borderBottom: '1px solid var(--border)' }}>
                <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 2 }}>{t}</div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', lineHeight: 1.5 }}>{desc}</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function AppShell() {
  // false until /api/library/status has answered. A persistent API failure
  // keeps it false and keeps retrying; the shell never opens on a guess.
  const [ready, setReady] = useState(false)
  const [slowStart, setSlowStart] = useState(false)
  // True only after GET /me itself answered 401. A network failure is not this.
  const [needsSignIn, setNeedsSignIn] = useState(false)
  const setSessionName = useSessionStore((s) => s.setName)
  const attemptsRef = useRef(0)
  const queryClient = useQueryClient()

  // Fetched once. fetchArchiveProfile never throws: a failure answers an empty
  // profile (the default title). The retry-after-reconnect invalidation in
  // `check` refetches it too.
  const { data: profileInfo, isLoading: profileLoading } = useQuery({
    queryKey: ['archive-profile'],
    queryFn: fetchArchiveProfile,
    staleTime: 60 * 60_000,
    retry: false,
  })
  const setProfile = useProfileStore((s) => s.setFromBackend)
  const title = profileInfo?.title || DEFAULT_TITLE
  useEffect(() => {
    if (profileInfo) setProfile(profileInfo)
  }, [profileInfo, setProfile])
  useEffect(() => {
    document.title = title
  }, [title])

  const check = useCallback(async () => {
    const BASE_DELAY_MS = 250
    const MAX_DELAY_MS = 3000
    // After ~3s of failures, supplement the splash with a Retry button. The
    // happy path responds in <100ms; if we're still failing at 3s the user
    // wants a signal and an escape hatch. We NEVER fall through to the
    // shell — `ready` only flips on a successful response.
    const SLOW_START_AFTER_MS = 3000

    const startedAt = Date.now()
    while (true) {
      try {
        await api.libraryStatus()
        // Backend just came back after failures: the profile fetch at startup
        // will have failed to the default title. Re-ask before leaving the
        // splash so the press's own name shows.
        if (attemptsRef.current > 0) {
          await queryClient.invalidateQueries({ queryKey: ['archive-profile'] })
        }
        setReady(true)
        setSlowStart(false)
        setNeedsSignIn(false)
        void fetchSession().then((s) => setSessionName(s.state === 'signed-in' ? s.name : null))
        // Successful libraryStatus after a transient failure is also a signal
        // the API came back online — invalidate any cached error states so
        // every other panel re-fetches fresh data instead of showing stale
        // "API unreachable" messages.
        if (attemptsRef.current > 0) {
          queryClient.invalidateQueries()
        }
        return
      } catch (e) {
        // Accounts exist and this browser has no session: show sign-in rather
        // than retrying 401s forever. Only /me answering 401 counts; any other
        // failure keeps retrying and never routes anywhere.
        if (e instanceof Error && /^401\b/.test(e.message) && (await fetchSession()).state === 'signed-out') {
          setNeedsSignIn(true)
          return
        }
        // Signed in, but this role may not read library status (the org gate
        // answers 404 for a writer). The backend answered, so open the shell
        // instead of retrying forever.
        if (e instanceof Error && /^(403|404)\b/.test(e.message)) {
          const s = await fetchSession()
          if (s.state === 'signed-in') {
            setSessionName(s.name)
            setReady(true)
            setSlowStart(false)
            return
          }
        }
        // Binding omitted deliberately: this is the indefinite startup retry,
        // and WHICH error occurred does not change the response — back off and
        // try again, surfacing the "taking longer than usual" affordance past
        // SLOW_START_AFTER_MS. Never open the shell on failure (see
        // the maintainer notes).
        attemptsRef.current += 1
        if (Date.now() - startedAt > SLOW_START_AFTER_MS) setSlowStart(true)
        const delay = Math.min(
          MAX_DELAY_MS,
          BASE_DELAY_MS * Math.pow(1.5, attemptsRef.current - 1),
        )
        await new Promise((r) => setTimeout(r, delay))
      }
    }
  }, [queryClient, setSessionName])

  useEffect(() => { check() }, [check])

  if (needsSignIn && !profileLoading) {
    return (
      <SignIn
        title={title}
        onSignedIn={(a) => {
          setSessionName(a.name)
          setNeedsSignIn(false)
          attemptsRef.current = 1 // so check() refetches what the 401s poisoned
          check()
        }}
      />
    )
  }

  if (!ready || profileLoading) {
    return (
      <div style={{ position: 'fixed', inset: 0, background: 'var(--bg-base)', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 16 }}>
        <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>Starting {title}…</div>
        {slowStart && (
          <div style={{ fontSize: 11, color: 'var(--text-muted)', textAlign: 'center', maxWidth: 360, lineHeight: 1.6 }}>
            <div>Taking longer than usual — the API container may still be building.</div>
            <button
              onClick={() => { attemptsRef.current = 0; setSlowStart(false); check() }}
              style={{ marginTop: 12, fontSize: 11, padding: '6px 12px', cursor: 'pointer' }}
            >
              Retry now
            </button>
            <div style={{ marginTop: 8 }}>
              Check logs: <code>./pillar43 logs</code>
            </div>
          </div>
        )}
      </div>
    )
  }

  return <Layout />
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <ConfirmProvider>
          <PromptProvider>
            <ConfirmDestructiveProvider>
            <AppShell />
            </ConfirmDestructiveProvider>
          </PromptProvider>
        </ConfirmProvider>
      </ToastProvider>
    </QueryClientProvider>
  )
}
