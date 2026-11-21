// ──────────────────────────────────────────────────────────────────────────────
// API Client — Modular decomposition (Sprint 6 Priority 1)
//
// Structure:
//   api/_fetch.ts     — shared req() utility + BASE constant
//   api/_types.ts     — all shared type definitions
//   api/files.ts      — file/folder operations (tree, CRUD, trash, history)
//   api.ts (this)     — re-exports everything for backward compatibility
//
// All existing imports like `import { api } from './lib/api'` continue to work.
// ──────────────────────────────────────────────────────────────────────────────

// Import and re-export domain modules
import { filesApi } from './api/files'
import { catalogApi } from './api/catalog'
import { aiApi } from './api/ai'
import { settingsApi } from './api/settings'
import { searchApi } from './api/search'

// Import and re-export all types (backward compat + avoid circular deps)
export type {
  CatalogStats,
  CatalogStatus,
  Task,
  Thread,
  TreeNode,
  FileContent,
  SearchResult,
  GraphNode,
  GraphStats,
  GraphEdge,
  GraphData,
  DuplicateIssue,
  DetritusIssue,
  ArchivistIssues,
  InboxItem,
  ConnectionLink,
  TopicCount,
  LinkSuggestion,
} from './api/_types'

export const api = {
  // ── Files (from api/files.ts) ────────────────────────────────────────────
  ...filesApi,

  // ── Catalog (from api/catalog.ts) ────────────────────────────────────────
  ...catalogApi,

  // ── AI (from api/ai.ts) ──────────────────────────────────────────────────
  ...aiApi,

  // ── Settings (from api/settings.ts) ──────────────────────────────────────
  ...settingsApi,

  // ── Search (from api/search.ts) ──────────────────────────────────────────
  ...searchApi,
}
