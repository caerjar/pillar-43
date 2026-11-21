/** The signed-in account in the org profile (null while open or unknown). */
import { create } from 'zustand'

interface SessionState {
  name: string | null
  /** admin, staff or writer; null until GET /me has answered. */
  role: string | null
  setName: (name: string | null) => void
  setRole: (role: string | null) => void
}

export const useSessionStore = create<SessionState>()((set) => ({
  name: null,
  role: null,
  setName: (name) => set({ name }),
  setRole: (role) => set({ role }),
}))
