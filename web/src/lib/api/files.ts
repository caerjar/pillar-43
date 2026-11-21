/**
 * File and folder operations API client.
 *
 * Covers: tree navigation, CRUD, trash, move/rename, history, backlinks.
 */

import type { TreeNode, FileContent, LinkSuggestion } from './_types'
import { req } from './_fetch'

export const filesApi = {
  // ── Tree & Navigation ──────────────────────────────────────────────────────

  tree: () => req<TreeNode[]>('/api/tree'),

  treeDir: (path: string) =>
    req<{ path: string; children: TreeNode[] }>(`/api/tree/dir?path=${encodeURIComponent(path)}`),

  fileCataloged: () => req<{ paths: string[] }>('/api/file/cataloged'),

  // ── Read ────────────────────────────────────────────────────────────────────

  readFile: (path: string) =>
    req<FileContent>(`/api/file?path=${encodeURIComponent(path)}`),

  fileText: (path: string) =>
    req<{ path: string; text: string | null }>(`/api/file/text?path=${encodeURIComponent(path)}`),

  findFile: (q: string) =>
    req<{ results: string[] }>(`/api/file/find?q=${encodeURIComponent(q)}`),

  annotationPath: (path: string) =>
    req<{ annotation_path: string }>(`/api/file/annotation-path?path=${encodeURIComponent(path)}`),

  // ── Write ───────────────────────────────────────────────────────────────────


  writeFile: (path: string, content: string) =>
    req<{ ok: boolean }>('/api/file', {
      method: 'POST',
      body: JSON.stringify({ path, content }),
    }),

  duplicateFile: (src: string, dest: string) =>
    req<{ src: string; dest: string; ok: boolean }>('/api/file/duplicate', {
      method: 'POST',
      body: JSON.stringify({ src, dest }),
    }),

  // ── Delete / Trash ──────────────────────────────────────────────────────────

  deleteFile: (path: string) =>
    req<{ ok: boolean }>(`/api/file?path=${encodeURIComponent(path)}`, {
      method: 'DELETE',
    }),

  trashFile: (path: string, applyLinks = false) =>
    req<{ path: string; trash_path: string; ok: boolean; modified_files: string[] }>('/api/file/trash', {
      method: 'POST',
      body: JSON.stringify({ path, apply_links: applyLinks }),
    }),

  restoreFile: (path: string) =>
    req<{ path: string; restored_to: string; ok: boolean }>('/api/file/restore', {
      method: 'POST',
      body: JSON.stringify({ path }),
    }),

  trashList: () =>
    req<{
      items: { trash_path: string; original: string; name: string; size_bytes: number; trashed_at: number }[]
    }>('/api/trash'),

  emptyTrash: () =>
    req<{ deleted: number; errors: { path: string; error: string }[] }>('/api/trash/empty', {
      method: 'POST',
    }),

  // ── Move / Rename ───────────────────────────────────────────────────────────

  moveFile: (src: string, dest: string, applyLinks = false) =>
    req<{ src: string; dest: string; ok: boolean; modified_files: string[] }>('/api/file/move', {
      method: 'POST',
      body: JSON.stringify({ src, dest, apply_links: applyLinks }),
    }),

  movePreview: (src: string, dest: string) =>
    req<{
      src: string
      dest: string
      changes: { file: string; line: number; old_text: string; new_text: string }[]
    }>(`/api/file/move/preview?src=${encodeURIComponent(src)}&dest=${encodeURIComponent(dest)}`),

  renameFile: (path: string, newName: string) =>
    req<{ path: string; new_path: string; ok: boolean }>('/api/file/rename', {
      method: 'POST',
      body: JSON.stringify({ path, new_name: newName }),
    }),

  // ── Folders ─────────────────────────────────────────────────────────────────

  createFolder: (path: string) =>
    req<{ path: string; ok: boolean }>('/api/folder', {
      method: 'POST',
      body: JSON.stringify({ path }),
    }),

  renameFolder: (path: string, newName: string) =>
    req<{ path: string; new_path: string; ok: boolean }>('/api/folder/rename', {
      method: 'POST',
      body: JSON.stringify({ path, new_name: newName }),
    }),

  moveFolder: (src: string, dest: string) =>
    req<{ src: string; dest: string; ok: boolean }>('/api/folder/move', {
      method: 'POST',
      body: JSON.stringify({ src, dest }),
    }),

  trashFolder: (path: string) =>
    req<{ path: string; trash_path: string; ok: boolean }>('/api/folder/trash', {
      method: 'POST',
      body: JSON.stringify({ path }),
    }),

  // ── Links & Backlinks ───────────────────────────────────────────────────────

  suggestLinks: (params: { q?: string; context?: string; exclude?: string; limit?: number }) => {
    const sp = new URLSearchParams()
    if (params.q !== undefined) sp.set('q', params.q)
    if (params.context) sp.set('context', params.context)
    if (params.exclude) sp.set('exclude', params.exclude)
    if (params.limit) sp.set('limit', String(params.limit))
    return req<{ query: string; results: LinkSuggestion[] }>(`/api/links/suggest?${sp.toString()}`)
  },

  fileBacklinks: (path: string, limit = 100) => {
    const params = new URLSearchParams()
    params.set('path', path)
    params.set('limit', String(limit))
    return req<{
      path: string
      inbound: Array<{ path: string; line: number; summary: string | null }>
      outbound: Array<{ path: string; line: number; summary: string | null }>
    }>(`/api/file/backlinks?${params.toString()}`)
  },

  // ── History ─────────────────────────────────────────────────────────────────

  fileHistory: (path: string, limit = 50) =>
    req<{
      path: string
      commits: { sha: string; short_sha: string; message: string; timestamp: string; author: string }[]
    }>(`/api/history?path=${encodeURIComponent(path)}&limit=${limit}`),

  historyContent: (path: string, commit: string) =>
    req<{ path: string; commit: string; content: string }>(
      `/api/history/content?path=${encodeURIComponent(path)}&commit=${encodeURIComponent(commit)}`
    ),

  historyRevert: (path: string, commit: string) =>
    req<{ path: string; reverted_to: string; new_sha: string }>('/api/history/revert', {
      method: 'POST',
      body: JSON.stringify({ path, commit }),
    }),
}
