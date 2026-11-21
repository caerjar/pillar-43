import { describe, it, expect, beforeEach } from 'vitest'
import { useAppStore } from './appStore'

// Reset store to a known state before each test
beforeEach(() => {
  useAppStore.setState({
    currentFile: null,
    leftTab: 'files',
    panelMode: 'normal',
    history: [],
    historyIndex: -1,
    recentFiles: [],
    maxRecentFiles: 50,
    jobs: [],
  })
})

describe('setCurrentFile — history', () => {
  it('sets currentFile and starts history', () => {
    const { setCurrentFile } = useAppStore.getState()
    setCurrentFile('library/a.md')
    const s = useAppStore.getState()
    expect(s.currentFile).toBe('library/a.md')
    expect(s.history).toEqual(['library/a.md'])
    expect(s.historyIndex).toBe(0)
  })

  it('appends successive files to history', () => {
    const { setCurrentFile } = useAppStore.getState()
    setCurrentFile('library/a.md')
    setCurrentFile('library/b.md')
    setCurrentFile('notes/c.md')
    const s = useAppStore.getState()
    expect(s.history).toEqual(['library/a.md', 'library/b.md', 'notes/c.md'])
    expect(s.historyIndex).toBe(2)
    expect(s.currentFile).toBe('notes/c.md')
  })

  it('does not push a duplicate if the same file is set again', () => {
    const { setCurrentFile } = useAppStore.getState()
    setCurrentFile('library/a.md')
    setCurrentFile('library/a.md')
    const s = useAppStore.getState()
    expect(s.history).toEqual(['library/a.md'])
    expect(s.historyIndex).toBe(0)
  })

  it('truncates forward history when navigating to a new file mid-stack', () => {
    const { setCurrentFile } = useAppStore.getState()
    setCurrentFile('library/a.md')
    setCurrentFile('library/b.md')
    setCurrentFile('library/c.md')
    // Go back two steps
    useAppStore.getState().goBack()
    useAppStore.getState().goBack()
    expect(useAppStore.getState().currentFile).toBe('library/a.md')
    // Now navigate somewhere new — forward history (b, c) should be gone
    setCurrentFile('library/x.md')
    const s = useAppStore.getState()
    expect(s.history).toEqual(['library/a.md', 'library/x.md'])
    expect(s.historyIndex).toBe(1)
  })

  it('handles null (clear selection) without pushing to history', () => {
    const { setCurrentFile } = useAppStore.getState()
    setCurrentFile('library/a.md')
    setCurrentFile(null)
    const s = useAppStore.getState()
    expect(s.currentFile).toBeNull()
    // history unchanged — null doesn't push
    expect(s.history).toEqual(['library/a.md'])
  })
})

describe('goBack', () => {
  it('navigates to the previous file', () => {
    const { setCurrentFile } = useAppStore.getState()
    setCurrentFile('library/a.md')
    setCurrentFile('library/b.md')
    useAppStore.getState().goBack()
    const s = useAppStore.getState()
    expect(s.currentFile).toBe('library/a.md')
    expect(s.historyIndex).toBe(0)
  })

  it('is a no-op when already at the beginning', () => {
    const { setCurrentFile } = useAppStore.getState()
    setCurrentFile('library/a.md')
    useAppStore.getState().goBack()
    useAppStore.getState().goBack()
    const s = useAppStore.getState()
    expect(s.currentFile).toBe('library/a.md')
    expect(s.historyIndex).toBe(0)
  })
})

describe('goForward', () => {
  it('navigates to the next file after going back', () => {
    const { setCurrentFile } = useAppStore.getState()
    setCurrentFile('library/a.md')
    setCurrentFile('library/b.md')
    useAppStore.getState().goBack()
    useAppStore.getState().goForward()
    const s = useAppStore.getState()
    expect(s.currentFile).toBe('library/b.md')
    expect(s.historyIndex).toBe(1)
  })

  it('is a no-op when already at the end of history', () => {
    const { setCurrentFile } = useAppStore.getState()
    setCurrentFile('library/a.md')
    setCurrentFile('library/b.md')
    useAppStore.getState().goForward()
    const s = useAppStore.getState()
    expect(s.currentFile).toBe('library/b.md')
    expect(s.historyIndex).toBe(1)
  })
})

describe('recentFiles — insertion order', () => {
  it('prepends new files in order opened', () => {
    const { setCurrentFile } = useAppStore.getState()
    setCurrentFile('notes/a.md')
    setCurrentFile('notes/b.md')
    setCurrentFile('notes/c.md')
    const paths = useAppStore.getState().recentFiles.map((e) => e.path)
    expect(paths).toEqual(['notes/c.md', 'notes/b.md', 'notes/a.md'])
  })

  it('does not reorder when re-opening an existing file', () => {
    const { setCurrentFile } = useAppStore.getState()
    setCurrentFile('notes/a.md')
    setCurrentFile('notes/b.md')
    setCurrentFile('notes/c.md')
    const before = useAppStore.getState().recentFiles.map((e) => e.path)
    setCurrentFile('notes/a.md') // re-visit oldest
    const after = useAppStore.getState().recentFiles.map((e) => e.path)
    expect(after).toEqual(before)
  })

  it('honors maxRecentFiles cap when adding new entries', () => {
    useAppStore.setState({ maxRecentFiles: 2 })
    const { setCurrentFile } = useAppStore.getState()
    setCurrentFile('notes/a.md')
    setCurrentFile('notes/b.md')
    setCurrentFile('notes/c.md')
    const paths = useAppStore.getState().recentFiles.map((e) => e.path)
    expect(paths).toEqual(['notes/c.md', 'notes/b.md'])
  })

  it('setMaxRecentFiles trims the list when shrinking the cap', () => {
    const { setCurrentFile, setMaxRecentFiles } = useAppStore.getState()
    setCurrentFile('notes/a.md')
    setCurrentFile('notes/b.md')
    setCurrentFile('notes/c.md')
    setMaxRecentFiles(2)
    const paths = useAppStore.getState().recentFiles.map((e) => e.path)
    expect(paths).toEqual(['notes/c.md', 'notes/b.md'])
    expect(useAppStore.getState().maxRecentFiles).toBe(2)
  })
})

describe('jobs', () => {
  it('addJob registers a new running job with startedAt', () => {
    const { addJob } = useAppStore.getState()
    addJob({ id: 'j1', label: 'Running Dive…', status: 'running' })
    const s = useAppStore.getState()
    expect(s.jobs).toHaveLength(1)
    expect(s.jobs[0].id).toBe('j1')
    expect(s.jobs[0].status).toBe('running')
    expect(s.jobs[0].startedAt).toBeGreaterThan(0)
  })

  it('updateJob patches status and progress', () => {
    const { addJob, updateJob } = useAppStore.getState()
    addJob({ id: 'j1', label: 'Indexing…', status: 'running' })
    updateJob('j1', { status: 'done', finishedAt: 1000 })
    const job = useAppStore.getState().jobs[0]
    expect(job.status).toBe('done')
    expect(job.finishedAt).toBe(1000)
  })

  it('clearFinishedJobs removes done and error jobs, keeps running', () => {
    const { addJob, clearFinishedJobs } = useAppStore.getState()
    addJob({ id: 'j1', label: 'Running', status: 'running' })
    addJob({ id: 'j2', label: 'Done', status: 'done' })
    addJob({ id: 'j3', label: 'Error', status: 'error' })
    clearFinishedJobs()
    const s = useAppStore.getState()
    expect(s.jobs).toHaveLength(1)
    expect(s.jobs[0].id).toBe('j1')
  })
})

describe('persisted leftTab migrations', () => {
  // The store's `merge` maps retired tab values onto live ones. Without a case
  // here, a user whose last session ended on that tab hydrates into a tab that
  // renders nothing at all — the rail shows no selection and the centre pane
  // is empty, with no error anywhere.
  //
  // Reached directly rather than through localStorage: `persist` reads storage
  // once at module load, which has already happened by the time a test runs.
  function migrate(persisted: Record<string, unknown>) {
    const opts = (useAppStore as unknown as {
      persist: { getOptions: () => { merge?: (p: unknown, c: unknown) => { leftTab: string } } }
    }).persist.getOptions()
    return opts.merge!(persisted, useAppStore.getState())
  }

  it.each(['settings', 'today', 'maintain', 'threads', 'graph', 'catalog'])(
    "sends a persisted '%s' tab to Files",
    (tab) => {
      expect(migrate({ leftTab: tab }).leftTab).toBe('files')
    },
  )

  it.each(['files', 'ask', 'explore', 'people', 'terms'])('leaves the live tab %s alone', (tab) => {
    expect(migrate({ leftTab: tab }).leftTab).toBe(tab)
  })
})
