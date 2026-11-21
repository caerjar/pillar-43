import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../../lib/api'
import { useAppStore } from '../../stores/appStore'
import { MoveConfirmModal } from './MoveConfirmModal'
import { useToast } from '../ui/Toast'

// Import types and utilities from decomposed modules
import {
  type SortOrder,
  type AppSettings,
  type PendingMove,
  type ExpandMode,
  DEFAULT_SETTINGS,
  SORT_OPTIONS,
} from './FileTreeTypes'

import { sortNodes } from './FileTreeHelpers'

import { EmptyWorkspace } from './EmptyWorkspace'

// Step-1 split: TreeNodeRow + its private FileIcon/actionBtnStyle helpers
import { TreeNodeRow } from './TreeNodeRow'
import { STALE_TIME } from '../../constants'
import { errorMessage } from '../../lib/errors'


export function FileTree() {
  const [collapseKey, setCollapseKey] = useState(0)
  const [expandMode, setExpandMode] = useState<ExpandMode>(null)
  const [sortOrder, setSortOrder] = useState<SortOrder>('name-asc')
  const [pendingMove, setPendingMove] = useState<PendingMove | null>(null)
  const qc = useQueryClient()
  const { setCurrentFile, currentFile } = useAppStore()
  const toast = useToast()

  const { data: appSettingsData } = useQuery({
    queryKey: ['app-settings'],
    queryFn: () => api.appSettings(),
    staleTime: STALE_TIME.ACTIVE,
  })

  const appSettings: AppSettings = (appSettingsData as AppSettings | undefined) ?? DEFAULT_SETTINGS

  const { data, isLoading, error } = useQuery({
    queryKey: ['tree'],
    queryFn: api.tree,
    staleTime: STALE_TIME.DEFAULT,
    gcTime: 60_000,
  })

  async function handleMoveConfirm(applyLinks: boolean) {
    if (!pendingMove) return
    const { src, dest } = pendingMove
    setPendingMove(null)
    try {
      await api.moveFile(src, dest, applyLinks)
      if (currentFile === src) setCurrentFile(dest)
      qc.invalidateQueries({ queryKey: ['tree'] })
    } catch (e) {
      toast.error(errorMessage(e))
    }
  }

  if (isLoading) {
    return <div style={{ padding: '12px 8px', color: 'var(--text-muted)', fontSize: 12 }}>Loading library…</div>
  }

  if (error) {
    return <div style={{ padding: '12px 8px', color: 'var(--error)', fontSize: 12 }}>Failed to load library</div>
  }

  const btnStyle: React.CSSProperties = {
    padding: '2px 7px',
    background: 'transparent',
    color: 'var(--text-muted)',
    border: '1px solid var(--border)',
    borderRadius: 3,
    cursor: 'pointer',
    fontSize: 11,
    flexShrink: 0,
  }

  const nodes = sortNodes(data ?? [], sortOrder)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, overflow: 'hidden' }} data-testid="file-tree">
      {/* Toolbar — single line: collapse / expand / sort */}
      <div style={{
        display: 'flex', gap: 4, padding: '5px 8px', flexShrink: 0,
        borderBottom: '1px solid var(--border)', alignItems: 'center',
        flexWrap: 'nowrap', overflow: 'hidden',
      }}>
        <button style={btnStyle} onClick={() => { setCollapseKey((k) => k + 1); setExpandMode(false) }} title="Collapse all">
          ⊟ all
        </button>
        <button style={btnStyle} onClick={() => { setCollapseKey((k) => k + 1); setExpandMode(true) }} title="Expand all">
          ⊞ all
        </button>
        <select
          value={sortOrder}
          onChange={(e) => setSortOrder(e.target.value as SortOrder)}
          title="Sort order"
          style={{
            background: 'var(--bg-active)',
            color: 'var(--text-muted)',
            border: '1px solid var(--border)',
            borderRadius: 3,
            padding: '2px 4px',
            fontSize: 11,
            cursor: 'pointer',
            outline: 'none',
            flexShrink: 0,
          }}
        >
          {SORT_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
        {!appSettings.library_readonly && (
          <span style={{ marginLeft: 'auto', fontSize: 9, color: 'var(--accent)', opacity: 0.7, flexShrink: 0 }}>vault editable</span>
        )}
      </div>

      <div style={{ padding: '4px 0', overflow: 'auto', flex: 1 }}>
        {nodes.length === 0 ? (
          <EmptyWorkspace />
        ) : (
          nodes.map((node) => (
            <TreeNodeRow
              key={`${node.path}-${collapseKey}`}
              node={node}
              depth={0}
              defaultOpen={expandMode ?? undefined}
              settings={appSettings}
              sortOrder={sortOrder}
              onPendingMove={setPendingMove}
            />
          ))
        )}
      </div>

      {pendingMove && (
        <MoveConfirmModal
          src={pendingMove.src}
          dest={pendingMove.dest}
          onConfirm={handleMoveConfirm}
          onCancel={() => setPendingMove(null)}
        />
      )}
    </div>
  )
}
