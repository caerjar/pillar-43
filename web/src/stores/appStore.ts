import { create } from 'zustand'
import { persist } from 'zustand/middleware'

// 'settings' was a member until 2026-08-30. Settings is now a Preferences
// window (Settings/SettingsWindow.tsx) rather than a pane, so it has its own
// `settingsOpen` flag below. Dropping it from the union is deliberate: tsc
// then enumerates every call site instead of leaving them to a hand search.
export type LeftTab = 'files' | 'ask' | 'explore' | 'people' | 'terms'
export const LEFT_TABS: readonly LeftTab[] = ['files', 'ask', 'explore', 'people', 'terms']
export type PanelId = LeftTab
export type PanelMode = 'normal' | 'focus'

export type JobStatus = 'running' | 'done' | 'error' | 'cancelled'

export interface Job {
  id: string
  label: string
  status: JobStatus
  progress?: string
  startedAt: number
  finishedAt?: number
  /** Optional kind tag: lets selectors filter without parsing labels. */
  kind?: string
}

export interface RecentEntry {
  path: string
  visitedAt: number
}

export interface AppError {
  /** Machine-readable code, e.g. 'billing_exhausted'. */
  code: string
  /** User-facing copy. */
  message: string
}

interface AppState {
  currentFile: string | null
  /** Where a citation asked the PDF viewer to open. Not persisted. */
  pdfTarget: { path: string; page: number; text?: string } | null
  selectedFolder: string | null
  leftTab: LeftTab
  /** Preferences window. Deliberately NOT persisted — see partialize. */
  settingsOpen: boolean
  /** Which group the window lands on. null = the first group. */
  settingsSection: string | null
  panelMode: PanelMode
  pendingEdit: boolean
  /** Set with setPendingLine; consumed by Editor on file mount, then cleared.
   * Used by anti-search ghost click and other "open at line N" navigation. */
  pendingLine: number | null
  lightMode: boolean
  history: string[]
  historyIndex: number
  recentFiles: RecentEntry[]
  maxRecentFiles: number
  jobs: Job[]
  /** Last fatal error from any backend call. Surfaced as a sticky toast by
   * useBillingAlert when code === 'billing_exhausted'. Other consumers may
   * read it too; clear with clearLastError. */
  lastError: AppError | null

  setCurrentFile: (path: string | null) => void
  setPdfTarget: (t: { path: string; page: number; text?: string } | null) => void
  setSelectedFolder: (path: string | null) => void
  setLeftTab: (tab: LeftTab) => void
  setActivePanel: (tab: LeftTab) => void
  openSettings: (section?: string) => void
  closeSettings: () => void
  setPendingEdit: (v: boolean) => void
  setPendingLine: (line: number | null) => void
  setLightMode: (v: boolean) => void
  setMaxRecentFiles: (n: number) => void
  toggleFocusMode: () => void
  goBack: () => void
  goForward: () => void
  addJob: (job: Omit<Job, 'startedAt'>) => void
  updateJob: (id: string, patch: Partial<Pick<Job, 'status' | 'progress' | 'finishedAt'>>) => void
  clearFinishedJobs: () => void
  setLastError: (err: AppError | null) => void
  clearLastError: () => void
}

export const useAppStore = create<AppState>()(
  persist(
    (set) => ({
      currentFile: null,
      pdfTarget: null,
      selectedFolder: null,
      // Fresh users land on Files (the file tree) with no file open, so the Home
      // renders in the center pane (Obsidian-homepage style) with the tree beside
      // it. Returning users keep their persisted tab.
      leftTab: 'files',
      settingsOpen: false,
      settingsSection: null,
      panelMode: 'normal',
      pendingEdit: false,
      pendingLine: null,
      lightMode: false,
      history: [],
      historyIndex: -1,
      recentFiles: [],
      maxRecentFiles: 50,
      jobs: [],
      lastError: null,

      setPdfTarget: (t) => set({ pdfTarget: t }),
      setCurrentFile: (path) =>
        set((s) => {
          if (!path) return { currentFile: null }
          if (path === s.currentFile) return {}
          const truncated = s.history.slice(0, s.historyIndex + 1)
          const history = [...truncated, path]
          // Insertion order: the Recent panel is a timeline of files first
          // opened, not most-recently visited. Re-opening an existing entry
          // does not reorder. New entries land at the top; cap is the
          // user-configured maxRecentFiles.
          const exists = s.recentFiles.some((e) => e.path === path)
          const recentFiles = exists
            ? s.recentFiles
            : [{ path, visitedAt: Date.now() }, ...s.recentFiles].slice(0, s.maxRecentFiles)
          return { currentFile: path, history, historyIndex: history.length - 1, recentFiles }
        }),

      setSelectedFolder: (path) => set({ selectedFolder: path }),

      setLeftTab: (tab) => set({ leftTab: tab }),

      setActivePanel: (tab) => set({ leftTab: tab }),

      openSettings: (section) => set({ settingsOpen: true, settingsSection: section ?? null }),

      closeSettings: () => set({ settingsOpen: false }),

      setPendingEdit: (v) => set({ pendingEdit: v }),

      setPendingLine: (line) => set({ pendingLine: line }),

      setLightMode: (v) => set({ lightMode: v }),

      setMaxRecentFiles: (n) =>
        set((s) => ({
          maxRecentFiles: n,
          recentFiles: s.recentFiles.slice(0, n),
        })),

      toggleFocusMode: () =>
        set((s) => ({ panelMode: s.panelMode === 'focus' ? 'normal' : 'focus' })),

      goBack: () =>
        set((s) => {
          if (s.historyIndex <= 0) return {}
          const idx = s.historyIndex - 1
          return { currentFile: s.history[idx], historyIndex: idx }
        }),

      goForward: () =>
        set((s) => {
          if (s.historyIndex >= s.history.length - 1) return {}
          const idx = s.historyIndex + 1
          return { currentFile: s.history[idx], historyIndex: idx }
        }),

      addJob: (job) =>
        set((s) => ({
          jobs: [...s.jobs, { ...job, startedAt: Date.now() }],
        })),

      updateJob: (id, patch) =>
        set((s) => ({
          jobs: s.jobs.map((j) => (j.id === id ? { ...j, ...patch } : j)),
        })),

      clearFinishedJobs: () =>
        set((s) => ({
          jobs: s.jobs.filter((j) => j.status === 'running'),
        })),

      setLastError: (err) => set({ lastError: err }),
      clearLastError: () => set({ lastError: null }),
    }),
    {
      name: 'pillar43-ui',
      partialize: (s) => ({
        // Only the view the person last had. Jobs are not persisted: they would
        // come back as stale `running` state from a previous session.
        leftTab: s.leftTab === 'ask' ? 'files' : s.leftTab,
        panelMode: s.panelMode,
        currentFile: s.currentFile,
        recentFiles: s.recentFiles,
        maxRecentFiles: s.maxRecentFiles,
        lightMode: s.lightMode,
      }),
      // Migrate old 'catalog'/'archivist' tab values to 'maintain'
      merge: (persisted: unknown, current) => {
        const p = persisted as Partial<typeof current>
        // A tab the app no longer has hydrates into a view that renders
        // nothing: the rail shows no selection and the centre pane is empty,
        // with no error anywhere. Land such people on the file tree.
        if (p.leftTab && !LEFT_TABS.includes(p.leftTab)) p.leftTab = 'files'
        return { ...current, ...p }
      },
    }
  )
)

