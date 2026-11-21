/**
 * Session state for Explore and People, so a result survives opening a
 * passage in Files and coming back. Not persisted.
 */
import { create } from 'zustand'
import type { ExploreResponse, PersonRecord } from '../../lib/api/archive'

interface ViewState {
  query: string
  explore: ExploreResponse | null
  exploreSelected: number | null
  personName: string | null
  person: PersonRecord | null
  personSelected: number | null
  /** The view a non-admin opened a whole file from, so the file has a way back. */
  returnTo: 'ask' | 'explore' | 'people' | null
  set: (patch: Partial<Omit<ViewState, 'set'>>) => void
}

export const useArchiveViews = create<ViewState>()((set) => ({
  query: '',
  explore: null,
  exploreSelected: null,
  personName: null,
  person: null,
  personSelected: null,
  returnTo: null,
  set: (patch) => set(patch),
}))
