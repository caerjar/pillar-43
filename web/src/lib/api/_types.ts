/**
 * Shared type definitions for all API modules.
 *
 * Extracted from api.ts to avoid circular dependencies when domain modules
 * (files.ts, catalog.ts, etc.) need to import types.
 */

// Re-export types from the centralized types/api.ts file
export type {
  CatalogStats,
  CatalogStatus,
  Task,
  Thread,
  TreeNode,
} from '../../types/api'

export interface FileContent {
  path: string
  content: string | null
  binary?: boolean
  ext?: string
  /** Backend refused to send the body — file exceeds MAX_EDITOR_BYTES.
   * `content` is null and `binary` is FALSE, so any consumer that branches
   * only on `binary` renders an empty editor over a real file. */
  too_large?: boolean
  size_mb?: number
  message?: string
}

export interface SearchResult {
  path: string
  line: number
  text: string
  source?: 'ripgrep' | 'catalog' | 'semantic'
  note?: string | null
}

// ── Graph types ──────────────────────────────────────────────────────────────

export interface GraphNode {
  id: string          // mount-prefixed path or "ghost:<name>"
  label: string       // filename stem
  path: string | null // null for ghost nodes
  thread: string      // parent thread dir name (for color clustering)
  kind: 'notes' | 'library' | 'ghost' | 'index' | 'thread' | 'generated'
  file_count?: number  // only present on thread-kind nodes
}

export interface GraphStats {
  node_count: number
  edge_count: number
  ghost_node_count: number
  index_node_count: number
  topic_edge_count: number
  wikilink_edge_count: number
  top_hubs: { path: string; label: string; degree: number }[]
  density: number
}

export interface GraphEdge {
  source: string
  target: string
  kind: 'wikilink' | 'topic_overlap' | 'vector_similar' | 'manual'
  score?: number
}

export interface GraphData {
  nodes: GraphNode[]
  edges: GraphEdge[]
  meta: { node_count: number; edge_count: number; has_catalog_data: boolean }
}

// ── Archivist types ──────────────────────────────────────────────────────────

export interface DuplicateIssue {
  file_a: string
  file_b: string
  score: number
  preview_a: string
  preview_b: string
  size_a: number
  size_b: number
  is_exact_duplicate: boolean
}

export interface DetritusIssue {
  path: string
  category: 'empty' | 'stub' | 'untitled' | 'very_old_stub'
  size_bytes: number
  mtime: number
  preview: string
  writable: boolean
}

export interface ArchivistIssues {
  duplicates: DuplicateIssue[]
  detritus: DetritusIssue[]
  stats: {
    near_duplicate_pairs: number
    exact_duplicate_groups: number
    detritus_files: number
    total_issues: number
  }
}

// ── Inbox types ──────────────────────────────────────────────────────────────

export interface InboxItem {
  path: string
  suggested_path: string | null
  summary: string
  topics: string[]
  size_bytes: number
  is_duplicate: boolean
  duplicate_of: string | null
}

// ── Connections ──────────────────────────────────────────────────────────────

export interface ConnectionLink {
  file_a: string
  file_b: string
  score: number
  kind: string
  shared_topics: string[]
  summary_a: string | null
  summary_b: string | null
}

export interface TopicCount {
  topic: string
  count: number
}

// ── Files ────────────────────────────────────────────────────────────────────

export interface LinkSuggestion {
  path: string
  title: string
  source: 'fuzzy' | 'semantic'
  score?: number
}
