import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { FileTree } from './FileTree'
import { useAppStore } from '../../stores/appStore'

vi.mock('../../lib/api', () => ({
  api: {
    tree: vi.fn().mockResolvedValue([
      { name: 'notes', path: 'notes', type: 'directory', children: [
        { name: 'notes', path: 'notes/notes', type: 'directory', children: [
          { name: 'note.md', path: 'notes/notes/note.md', type: 'file' },
        ]},
      ]},
      { name: 'library', path: 'library', type: 'directory', children: [] },
    ]),
    treeDir: vi.fn().mockResolvedValue({ path: '', children: [] }),
    appSettings: vi.fn().mockResolvedValue({ library_readonly: true, move_confirm: 'confirm', paths: { library_root: '/library', notes_path: '/notes', generated_path: '/generated' } }),
  },
}))

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

beforeEach(() => {
  useAppStore.setState({ currentFile: null, leftTab: 'files', panelMode: 'normal', history: [], historyIndex: -1 })
})

describe('FileTree', () => {
  it('renders the file tree after loading', async () => {
    wrap(<FileTree />)
    expect(await screen.findByTestId('tree-node-notes')).toBeDefined()
    expect(await screen.findByTestId('tree-node-library')).toBeDefined()
  })

  it('shows collapse-all and expand-all buttons', async () => {
    wrap(<FileTree />)
    await screen.findByTestId('tree-node-notes') // wait for load
    expect(screen.getByTitle('Collapse all')).toBeDefined()
    expect(screen.getByTitle('Expand all')).toBeDefined()
  })

  it('collapse-all button is clickable', async () => {
    const user = userEvent.setup()
    wrap(<FileTree />)
    await screen.findByTestId('tree-node-notes')
    const collapseBtn = screen.getByTitle('Collapse all')
    await user.click(collapseBtn)
    // After collapse, child nodes should not be visible
    expect(screen.queryByTestId('tree-node-notes/notes')).toBeNull()
  })

  it('expand-all button is clickable', async () => {
    const user = userEvent.setup()
    wrap(<FileTree />)
    await screen.findByTestId('tree-node-notes')
    const expandBtn = screen.getByTitle('Expand all')
    await user.click(expandBtn)
    // After expand, child nodes should be visible
    expect(await screen.findByTestId('tree-node-notes/notes')).toBeDefined()
  })
})
