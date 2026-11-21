/**
 * The press's name, as the backend reports it.
 *
 * A separate store, not part of `appStore`: it is not persisted (the backend
 * is the authority every start) and the components that read it are rendered
 * in tests without a QueryClientProvider, so they cannot call `useQuery`
 * themselves. `AppShell` fetches once and writes here.
 */
import { create } from 'zustand'
import type { ArchiveProfile } from '../lib/api/archive'

export const DEFAULT_TITLE = 'Local Archive'

interface ProfileState {
  title: string
  orgName: string
  setFromBackend: (p: ArchiveProfile) => void
}

export const useProfileStore = create<ProfileState>()((set) => ({
  title: DEFAULT_TITLE,
  orgName: '',
  setFromBackend: (p) => set({ title: p.title || DEFAULT_TITLE, orgName: p.org_name ?? '' }),
}))
