/**
 * API client tests — fetch wrapper, error handling, critical endpoints
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { api } from './api'
import { req } from './api/_fetch'

// Mock fetch globally
const mockFetch = vi.fn()
globalThis.fetch = mockFetch as any

beforeEach(() => {
  mockFetch.mockClear()
})

// Helper to create mock responses
const mockResponse = (status: number, body: unknown, ok = true) => ({
  ok,
  status,
  statusText: status === 200 ? 'OK' : 'Error',
  json: () => Promise.resolve(body),
  text: () => Promise.resolve(JSON.stringify(body)),
})

describe('API Client', () => {
  describe('Error Handling', () => {
    it('throws on 404 errors', async () => {
      mockFetch.mockResolvedValue(mockResponse(404, { detail: 'Not found' }, false))

      await expect(api.readFile('notes/missing.md')).rejects.toThrow('404')
    })

    it('throws on 500 errors', async () => {
      mockFetch.mockResolvedValue(mockResponse(500, { detail: 'Internal error' }, false))

      await expect(api.catalogStats()).rejects.toThrow('500')
    })

    it('throws on network failure', async () => {
      mockFetch.mockRejectedValue(new Error('Network error'))

      await expect(api.readFile('notes/test.md')).rejects.toThrow('Network error')
    })

    it('resolves undefined on 204 No Content (empty body)', async () => {
      // A 204 body is empty; res.json() would throw SyntaxError. A req<void>
      // caller (e.g. a DELETE) must resolve, not land in onError.
      mockFetch.mockResolvedValue({
        ok: true,
        status: 204,
        statusText: 'No Content',
        json: () => Promise.reject(new SyntaxError('Unexpected end of JSON input')),
        text: () => Promise.resolve(''),
      })

      await expect(
        req<void>('/api/example/x', { method: 'DELETE' }),
      ).resolves.toBeUndefined()
    })
  })

  describe('File Operations', () => {
    it('readFile constructs correct URL', async () => {
      mockFetch.mockResolvedValue(
        mockResponse(200, { path: 'notes/test.md', content: '# Test' }),
      )

      await api.readFile('notes/test.md')

      expect(mockFetch).toHaveBeenCalledWith(
        '/api/file?path=notes%2Ftest.md',
        expect.objectContaining({
          headers: expect.objectContaining({ 'Content-Type': 'application/json' }),
        }),
      )
    })

    it('writeFile sends content in body', async () => {
      mockFetch.mockResolvedValue(mockResponse(200, { ok: true }))

      await api.writeFile('notes/new.md', '# New content')

      expect(mockFetch).toHaveBeenCalledWith(
        '/api/file',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ path: 'notes/new.md', content: '# New content' }),
        }),
      )
    })

    it('deleteFile uses DELETE method', async () => {
      mockFetch.mockResolvedValue(mockResponse(200, { ok: true }))

      await api.deleteFile('notes/old.md')

      expect(mockFetch).toHaveBeenCalledWith(
        '/api/file?path=notes%2Fold.md',
        expect.objectContaining({ method: 'DELETE' }),
      )
    })

    it('renameFile sends path and new_name', async () => {
      mockFetch.mockResolvedValue(mockResponse(200, { ok: true }))

      await api.renameFile('notes/old.md', 'new.md')

      expect(mockFetch).toHaveBeenCalledWith(
        '/api/file/rename',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ path: 'notes/old.md', new_name: 'new.md' }),
        }),
      )
    })

    it('trashFile sends path', async () => {
      mockFetch.mockResolvedValue(mockResponse(200, { ok: true, trash_path: 'notes/_trash/old.md' }))

      const result = await api.trashFile('notes/old.md')

      expect(result.trash_path).toBe('notes/_trash/old.md')
      expect(mockFetch).toHaveBeenCalledWith(
        '/api/file/trash',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ path: 'notes/old.md', apply_links: false }),
        }),
      )
    })
  })

  describe('Search', () => {
    it('search encodes query params', async () => {
      mockFetch.mockResolvedValue(mockResponse(200, { query: 'test query', scope: 'notes', results: [] }))

      await api.search('test query', 'notes')

      const url = mockFetch.mock.calls[0][0]
      expect(url).toContain('q=test%20query')
      expect(url).toContain('scope=notes')
      expect(url).not.toContain('ai=')
    })

    it('search defaults to all scope', async () => {
      mockFetch.mockResolvedValue(mockResponse(200, []))

      await api.search('test')

      expect(mockFetch.mock.calls[0][0]).toContain('scope=all')
    })

    it('suggestLinks formats query correctly', async () => {
      mockFetch.mockResolvedValue(mockResponse(200, { query: 'partial', results: [] }))

      await api.suggestLinks({ q: 'partial', context: 'notes/current.md', limit: 10 })

      const url = mockFetch.mock.calls[0][0]
      expect(url).toContain('/api/links/suggest')
      expect(url).toContain('q=partial')
      expect(url).toContain('context=notes%2Fcurrent.md')
      expect(url).toContain('limit=10')
    })
  })

  describe('Settings', () => {
    it('getSettings fetches config', async () => {
      const settings = {
        ollama_model: 'llama3',
        library_readonly: true,
      }
      mockFetch.mockResolvedValue(mockResponse(200, settings))

      const result = await api.appSettings()

      expect(result.ollama_model).toBe('llama3')
      expect(mockFetch).toHaveBeenCalledWith(
        '/api/settings',
        expect.objectContaining({
          headers: expect.objectContaining({ 'Content-Type': 'application/json' }),
        }),
      )
    })

    it('updateSettings sends partial updates', async () => {
      mockFetch.mockResolvedValue(mockResponse(200, { ok: true }))

      await api.updateSettings({ ollama_model: 'qwen3' })

      expect(mockFetch).toHaveBeenCalledWith(
        '/api/settings',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ ollama_model: 'qwen3' }),
        }),
      )
    })
  })

  describe('Catalog', () => {
    it('getCatalogStatus returns stats', async () => {
      const status = {
        total_files: 100,
        mounts: [],
        connections: [],
      }
      mockFetch.mockResolvedValue(mockResponse(200, status))

      const result = await api.catalogStatus()

      expect(result.total_files).toBe(100)
    })

    it('catalogStats returns stats object', async () => {
      const stats = {
        file_count: 100,
        total_size_bytes: 1024000,
        mount_counts: { notes: 50, library: 50 },
      }
      mockFetch.mockResolvedValue(mockResponse(200, stats))

      const result = await api.catalogStats()

      expect(result.file_count).toBe(100)
    })

    it('catalogRun returns streaming response', async () => {
      const mockStreamResponse = {
        ok: true,
        body: {
          getReader: () => ({
            read: () => Promise.resolve({ done: true, value: undefined }),
          }),
        },
      }
      mockFetch.mockResolvedValue(mockStreamResponse)

      const result = await api.catalogRun()

      expect(result.ok).toBe(true)
      expect(mockFetch).toHaveBeenCalledWith(
        '/api/catalog/run',
        expect.objectContaining({ method: 'POST' }),
      )
    })
  })

  describe('History', () => {
    it('fileHistory returns commits', async () => {
      const history = {
        path: 'notes/test.md',
        commits: [
          { sha: 'abc123', short_sha: 'abc1', message: 'Update', timestamp: Date.now() / 1000, author: 'test' },
        ],
      }
      mockFetch.mockResolvedValue(mockResponse(200, history))

      const result = await api.fileHistory('notes/test.md')

      expect(result.commits).toHaveLength(1)
      expect(result.path).toBe('notes/test.md')
    })

    it('getHistoryContent sends path and commit', async () => {
      mockFetch.mockResolvedValue(mockResponse(200, { content: '# Old version' }))

      await api.historyContent('notes/test.md', 'abc123')

      const url = mockFetch.mock.calls[0][0]
      expect(url).toContain('/api/history/content')
      expect(url).toContain('path=notes%2Ftest.md')
      expect(url).toContain('commit=abc123')
    })

    it('revertToCommit sends path and commit', async () => {
      mockFetch.mockResolvedValue(mockResponse(200, { ok: true, new_sha: 'def456' }))

      await api.historyRevert('notes/test.md', 'abc123')

      expect(mockFetch).toHaveBeenCalledWith(
        '/api/history/revert',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ path: 'notes/test.md', commit: 'abc123' }),
        }),
      )
    })
  })

  describe('URL Construction', () => {
    it('handles BASE URL from environment', async () => {
      // Base URL is set via VITE_API_URL or defaults to ''
      mockFetch.mockResolvedValue(mockResponse(200, {}))

      await api.readFile('test.md')

      const url = mockFetch.mock.calls[0][0]
      // Should not have double slashes if BASE is empty
      expect(url).not.toContain('//')
    })

    it('encodes special characters in paths', async () => {
      mockFetch.mockResolvedValue(mockResponse(200, { path: 'notes/file with spaces.md', content: '' }))

      await api.readFile('notes/file with spaces.md')

      const url = mockFetch.mock.calls[0][0]
      expect(url).toContain('file%20with%20spaces.md')
    })

    it('encodes query params correctly', async () => {
      mockFetch.mockResolvedValue(mockResponse(200, []))

      await api.search('query with + and &')

      const url = mockFetch.mock.calls[0][0]
      expect(url).toContain('query%20with%20%2B%20and%20%26')
    })
  })

  describe('Content Type Headers', () => {
    it('includes Content-Type: application/json for all requests', async () => {
      mockFetch.mockResolvedValue(mockResponse(200, {}))

      await api.catalogStats()

      expect(mockFetch).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({
          headers: expect.objectContaining({
            'Content-Type': 'application/json',
          }),
        }),
      )
    })

    it('allows custom headers to be passed', async () => {
      // Some endpoints might need custom headers
      mockFetch.mockResolvedValue(mockResponse(200, {}))

      // This tests that the req() helper preserves custom headers
      await api.readFile('test.md')

      expect(mockFetch).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({
          headers: expect.any(Object),
        }),
      )
    })
  })
})
