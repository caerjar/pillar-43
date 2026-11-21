/**
 * Frontend type contract for backend response models.
 *
 * Each interface here mirrors a Pydantic class in `api/models/responses.py`
 * field-by-field. When a backend model changes, update both files in the
 * same commit. There is intentionally no codegen — these are hand-written
 * shapes the human + reviewer can diff against.
 *
 * Source of truth: `api/models/responses.py`.
 *
 * Endpoints currently covered:
 *   GET /api/threads        → ThreadsResponse  { threads: Thread[] }
 *   GET /api/tasks          → TasksResponse    { tasks: Task[] }
 *   GET /api/tree           → TreeNode[]       (RootModel — bare list on the wire)
 *   GET /api/catalog/status → CatalogStatus
 *   GET /api/catalog/stats  → CatalogStats
 */

// ── Threads ──────────────────────────────────────────────────────────────────

/** Mirrors `api/models/responses.py:ThreadOut`. */
export interface Thread {
  name: string
  topic: string
  status: 'alive' | 'latent' | 'dormant' | null
  status_override: 'alive' | 'latent' | 'dormant' | null
  file_count: number
  last_active: number | null
  files: string[]
  path: string | null
  has_file: boolean
  updated_at: number | null
  source: 'ai' | 'folder'
  priority: 'high' | 'normal' | 'low'
}

export interface ThreadsResponse {
  threads: Thread[]
}

// ── Tasks ────────────────────────────────────────────────────────────────────

/** Mirrors `api/models/responses.py:TaskOut`. */
export interface Task {
  path: string
  line: number
  text: string
  done: boolean
  writable: boolean
  /** ISO-8601 string in tasks table; some legacy rows carry float epoch. */
  created_at: string | number | null
  completed_at: string | number | null
  priority: 'high' | 'medium' | 'low' | string | null
  category: string | null
  due_date: string | null
  recurrence: 'daily' | 'weekly' | 'monthly' | string | null
  source: string
}

export interface TasksResponse {
  tasks: Task[]
}

// ── Tree ─────────────────────────────────────────────────────────────────────

/** Mirrors `api/models/responses.py:TreeNode`. */
export interface TreeNode {
  name: string
  path: string
  type: 'file' | 'directory'
  mtime: number
  ctime: number
  /** null = directory whose children haven't been loaded yet. Absent for files. */
  children?: TreeNode[] | null
}

// ── Catalog ──────────────────────────────────────────────────────────────────

/** Mirrors `api/models/responses.py:MountStatusOut`. */
export interface MountStatus {
  mount: string
  file_count: number
  last_summarized: number | null
}

/** Mirrors `api/models/responses.py:ConnectionCountOut`. */
export interface ConnectionCount {
  kind: string
  count: number
}

/** Mirrors `api/models/responses.py:CatalogStatus`. */
export interface CatalogStatus {
  total_files: number
  mounts: MountStatus[]
  connections: ConnectionCount[]
  thread_count?: number | null
  last_scan?: number | string | null
  interrupted?: boolean | null
  /** Present when the route's DB query raised; happy path omits it. */
  error?: string | null
}

/** Mirrors `api/models/responses.py:CatalogStats`. */
export interface CatalogStats {
  file_count: number
  last_indexed: string | number | null
  interrupted: boolean
  /** Non-null when stats couldn't be read (DB busy/unavailable). Treat as
   *  "unknown" — NOT "0 files / empty vault". */
  error?: string | null
}

// ── Agent Harness (Sprint 94) ────────────────────────────────────────────────

/** Mirrors `api/models/responses.py:AgentOut`. */
export interface Agent {
  slug: string
  name: string
  role: string
  voice: string
  color: string
  model: string
  tools: string[]
  metadata: Record<string, unknown>
  core_stance: string
  memory: string
  raw_path: string
}

export interface AgentsResponse {
  agents: Agent[]
}
