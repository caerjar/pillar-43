/**
 * Session state of the Ask view. In a store so the answers survive switching
 * to Files and back. Not persisted: past questions are for this session only.
 */
import { create } from 'zustand'
import type { AskResponse } from '../lib/api/archive'

interface AskState {
  history: AskResponse[]       // newest first
  activeIndex: number | null   // index into history
  pending: string | null       // question being answered
  error: string | null
  setPending: (q: string | null) => void
  setError: (e: string | null) => void
  addAnswer: (r: AskResponse) => void
  show: (i: number) => void
}

export const useAskStore = create<AskState>()((set) => ({
  history: [],
  activeIndex: null,
  pending: null,
  error: null,
  setPending: (pending) => set({ pending }),
  setError: (error) => set({ error }),
  addAnswer: (r) => set((s) => ({ history: [r, ...s.history], activeIndex: 0, pending: null, error: null })),
  show: (i) => set({ activeIndex: i, error: null }),
}))
