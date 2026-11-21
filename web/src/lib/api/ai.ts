/**
 * AI operations API client.
 *
 * Covers: chat, folder generation, classification, local models.
 */

import { BASE, req } from './_fetch'

export const aiApi = {
  // ── Chat ─────────────────────────────────────────────────────────────────

  chat: (messages: { role: string; content: string }[], fileContext = '', system = '') =>
    fetch(BASE + '/api/ai/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages, file_context: fileContext, system }),
    }),

  // ── Folder Generation ────────────────────────────────────────────────────

  folderGenerate: (params: {
    folder_path: string
    mode: string
    custom_prompt?: string
    output_path: string
    recursive?: boolean
  }) =>
    fetch(BASE + '/api/ai/folder/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params),
    }),

  // ── Classification ───────────────────────────────────────────────────────

  classify: (title: string, content: string, threadNames: string[]) =>
    req<{ threads: string[]; new_thread: string | null; rationale: string }>(
      '/api/ai/classify', {
        method: 'POST',
        body: JSON.stringify({ title, content, thread_names: threadNames }),
      }
    ),

  // ── Local Models ─────────────────────────────────────────────────────────

  localModels: () =>
    req<{ models: string[]; error: string | null }>('/api/ai/local-models'),
}
