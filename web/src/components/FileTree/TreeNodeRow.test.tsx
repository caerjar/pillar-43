/**
 * Tests for TreeNodeRow's mutation handlers.
 *
 * This file is the documented prerequisite for extracting
 * `useFileTreeNodeHandlers` — the maintainer notes says never decompose untested code,
 * and TreeNodeRow (863 LOC, six mutation handlers) had no test of its own.
 * FileTree.test.tsx renders it, but mocks `../../lib/api` down to tree /
 * treeDir / appSettings and never exercises a mutation.
 *
 * What is pinned here is what an extraction is most likely to drop silently:
 *
 *  - every handler invalidates ['tree'] on success. Miss one and the sidebar
 *    just stops updating after that operation, with no error anywhere.
 *  - handleTrash clears currentFile, but ONLY when the trashed node is the
 *    open one. A conditional store write is easy to turn into an
 *    unconditional one during a move.
 *  - the confirm() gate on both trash paths must short-circuit BEFORE the API
 *    call. Getting that backwards deletes a file the user declined to delete.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { TreeNodeRow } from './TreeNodeRow'
import { useAppStore } from '../../stores/appStore'
import type { TreeNode } from '../../lib/api/_types'

const api = {
  trashFile: vi.fn().mockResolvedValue({}),
  trashFolder: vi.fn().mockResolvedValue({}),
  renameFile: vi.fn().mockResolvedValue({}),
  renameFolder: vi.fn().mockResolvedValue({}),
  createFolder: vi.fn().mockResolvedValue({}),
  duplicateFile: vi.fn().mockResolvedValue({ path: 'notes/note copy.md' }),
  moveFile: vi.fn().mockResolvedValue({}),
  moveFolder: vi.fn().mockResolvedValue({}),
  treeDir: vi.fn().mockResolvedValue({ path: '', children: [] }),
}
vi.mock('../../lib/api', () => ({ api: new Proxy({}, { get: (_t, k) => (api as never)[k] }) }))

// confirm() is a promise-returning modal; the handlers await it before
// touching the API. Controlled per-test so the gate can be exercised.
const confirmResult = { value: true }
vi.mock('../ui/Confirm', () => ({
  useConfirm: () => () => Promise.resolve(confirmResult.value),
}))

const toastError = vi.fn()
vi.mock('../ui/Toast', () => ({
  useToast: () => ({ error: toastError, toast: vi.fn(), success: vi.fn(), warning: vi.fn(), info: vi.fn() }),
}))

const SETTINGS = {
  library_readonly: true,
  move_confirm: 'instant',
  paths: { library_root: '/library', notes_path: '/notes', generated_path: '/generated' },
} as never

// mtime/ctime are required on TreeNode and drive the sort comparators.
const fileNode = { name: 'note.md', path: 'notes/note.md', type: 'file', mtime: 0, ctime: 0 } as TreeNode
const dirNode = { name: 'sub', path: 'notes/sub', type: 'directory', children: [], mtime: 0, ctime: 0 } as TreeNode

let invalidateSpy: ReturnType<typeof vi.fn>

function wrap(node: TreeNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  invalidateSpy = vi.fn()
  qc.invalidateQueries = invalidateSpy as never
  return render(
    <QueryClientProvider client={qc}>
      <TreeNodeRow
        node={node}
        depth={0}
        settings={SETTINGS}
        sortOrder="name-asc"
        onPendingMove={vi.fn()}
      />
    </QueryClientProvider>,
  )
}

/** Open the row's context menu and click a labelled item. */
async function invokeMenuItem(user: ReturnType<typeof userEvent.setup>, label: string | RegExp) {
  const row = screen.getByTestId(/tree-node-/)
  await user.pointer({ keys: '[MouseRight]', target: row })
  const item = await screen.findByText(label)
  await user.click(item)
}

beforeEach(() => {
  vi.clearAllMocks()
  confirmResult.value = true
  useAppStore.setState({ currentFile: null, leftTab: 'files', panelMode: 'normal', history: [], historyIndex: -1 })
})

describe('TreeNodeRow mutation handlers', () => {
  it('trashing a file calls the API and invalidates the tree', async () => {
    const user = userEvent.setup()
    wrap(fileNode)
    await invokeMenuItem(user, 'Move to trash')

    await waitFor(() => expect(api.trashFile).toHaveBeenCalled())
    expect(api.trashFile.mock.calls[0][0]).toBe('notes/note.md')
    await waitFor(() =>
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['tree'] }),
    )
  })

  it('trashing the OPEN file clears currentFile', async () => {
    useAppStore.setState({ currentFile: 'notes/note.md' })
    const user = userEvent.setup()
    wrap(fileNode)
    await invokeMenuItem(user, 'Move to trash')

    await waitFor(() => expect(useAppStore.getState().currentFile).toBeNull())
  })

  it('trashing a DIFFERENT file leaves currentFile alone', async () => {
    useAppStore.setState({ currentFile: 'notes/other.md' })
    const user = userEvent.setup()
    wrap(fileNode)
    await invokeMenuItem(user, 'Move to trash')

    await waitFor(() => expect(api.trashFile).toHaveBeenCalled())
    expect(useAppStore.getState().currentFile).toBe('notes/other.md')
  })

  it('declining the confirm does not call the API at all', async () => {
    confirmResult.value = false
    const user = userEvent.setup()
    wrap(fileNode)
    await invokeMenuItem(user, 'Move to trash')

    await new Promise((r) => setTimeout(r, 0))
    expect(api.trashFile).not.toHaveBeenCalled()
    expect(invalidateSpy).not.toHaveBeenCalledWith({ queryKey: ['tree'] })
  })

  it('trashing a folder uses trashFolder and invalidates the tree', async () => {
    const user = userEvent.setup()
    wrap(dirNode)
    await invokeMenuItem(user, 'Move folder to trash')

    await waitFor(() => expect(api.trashFolder).toHaveBeenCalledWith('notes/sub'))
    await waitFor(() =>
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['tree'] }),
    )
  })

  it('declining the folder confirm does not call the API', async () => {
    confirmResult.value = false
    const user = userEvent.setup()
    wrap(dirNode)
    await invokeMenuItem(user, 'Move folder to trash')

    await new Promise((r) => setTimeout(r, 0))
    expect(api.trashFolder).not.toHaveBeenCalled()
  })

  it('a failing trash surfaces a toast and does NOT invalidate', async () => {
    api.trashFile.mockRejectedValueOnce(new Error('disk full'))
    const user = userEvent.setup()
    wrap(fileNode)
    await invokeMenuItem(user, 'Move to trash')

    await waitFor(() => expect(toastError).toHaveBeenCalledWith('disk full'))
    expect(invalidateSpy).not.toHaveBeenCalledWith({ queryKey: ['tree'] })
  })
})
