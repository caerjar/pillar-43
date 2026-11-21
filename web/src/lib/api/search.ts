/**
 * Search API client.
 *
 * Covers: ripgrep search across notes/library/generated.
 */

import type { SearchResult } from './_types'
import { req } from './_fetch'

export const searchApi = {
  search: (q: string, scope = 'all', threadFolder?: string, semantic = false) =>
    req<{ query: string; scope: string; results: SearchResult[]; semantic?: boolean }>(
      `/api/search?q=${encodeURIComponent(q)}&scope=${scope}${threadFolder ? `&thread_folder=${encodeURIComponent(threadFolder)}` : ''}${semantic ? '&semantic=true' : ''}`
    ),
}
