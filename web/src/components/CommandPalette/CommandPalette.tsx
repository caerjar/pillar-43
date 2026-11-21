import { useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { api } from '../../lib/api'
import { useAppStore } from '../../stores/appStore'
import { useSessionStore } from '../../stores/sessionStore'
import { useCommandCtx } from '../../lib/menu/useCommandCtx'
import { buildCommands, scoreCommand } from './commands'

interface Props {
  onClose: () => void
}

const MAX_RESULTS = 20

/**
 * Command palette — ⌘P. Fuzzy-matches over registered commands and
 * indexed file paths. Three result groups (commands first, files second).
 */
export function CommandPalette({ onClose }: Props) {
  const setCurrentFile = useAppStore((s) => s.setCurrentFile)
  // One shared context, built in one place — see `lib/menu/useCommandCtx.ts`.
  const commandCtx = useCommandCtx()

  const recentEntries = useAppStore((s) => s.recentFiles)
  const recentFilePaths = useMemo(
    () => recentEntries.slice(0, 10).map((e) => e.path),
    [recentEntries],
  )

  const [query, setQuery] = useState('')
  const [files, setFiles] = useState<string[]>([])
  const [selected, setSelected] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)

  const isWriter = useSessionStore((s) => s.role === 'writer')
  const commands = useMemo(
    () => buildCommands({ recentFiles: recentFilePaths, canOpenSettings: !isWriter }),
    [recentFilePaths, isWriter],
  )

  // Load dynamic data once when the palette opens. Each fetch is independent —
  // a failure in one doesn't blank the rest.
  useEffect(() => {
    inputRef.current?.focus()
    let alive = true
    api.fileCataloged()
      .then((data) => alive && setFiles(data.paths ?? []))
      .catch(() => {})
    return () => {
      alive = false
    }
  }, [])

  const matches = useMemo(() => {
    const q = query.trim()
    // When query is empty, show the first 8 recent commands and skip the
    // long thread/skill lists — the empty palette would otherwise dump
    // hundreds of rows. Once the user types, the score filter handles it.
    const scoredCmds = commands
      .map((c) => ({ cmd: c, score: scoreCommand(c, q) }))
      .filter((m) => {
        if (q === '') {
          // No query: show only static (non-dynamic) sections
          return ['navigate', 'view', 'theme'].includes(m.cmd.section)
        }
        return m.score > -1
      })
      .sort((a, b) => b.score - a.score)
      .slice(0, MAX_RESULTS)

    const fileMatches = q
      ? files
          .map((p) => {
            const lower = p.toLowerCase()
            const ql = q.toLowerCase()
            if (lower === ql) return { path: p, score: 1000 }
            const idx = lower.indexOf(ql)
            if (idx >= 0) return { path: p, score: 500 - idx }
            // subsequence match
            let qi = 0
            for (let i = 0; i < lower.length && qi < ql.length; i++) {
              if (lower[i] === ql[qi]) qi++
            }
            return qi === ql.length ? { path: p, score: 100 } : null
          })
          .filter((m): m is { path: string; score: number } => m !== null)
          .sort((a, b) => b.score - a.score)
          .slice(0, MAX_RESULTS)
      : []

    return { commands: scoredCmds, files: fileMatches }
  }, [query, commands, files])

  const flat = useMemo(
    () => [
      ...matches.commands.map((m) => ({ kind: 'command' as const, cmd: m.cmd })),
      ...matches.files.map((m) => ({ kind: 'file' as const, path: m.path })),
    ],
    [matches],
  )

  // Reset selection when results change
  useEffect(() => {
    setSelected(0)
  }, [query])

  function execute(idx: number) {
    const item = flat[idx]
    if (!item) return
    onClose()
    if (item.kind === 'command') {
      // `useCommandCtx` rather than an inline object. This site built its own
      // and drifted the moment the menu gained confirm/prompt/invalidate —
      // which is the exact failure that hook's docstring was written about.
      void item.cmd.action(commandCtx)
    } else {
      setCurrentFile(item.path)
    }
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Escape') {
      e.preventDefault()
      onClose()
    } else if (e.key === 'ArrowDown') {
      e.preventDefault()
      setSelected((s) => Math.min(s + 1, flat.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setSelected((s) => Math.max(s - 1, 0))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      execute(selected)
    }
  }

  let renderIdx = 0
  return createPortal(
    <div
      role="presentation"
      onClick={onClose}
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0, 0, 0, 0.45)',
        display: 'flex',
        justifyContent: 'center',
        paddingTop: '12vh',
        zIndex: 1000,
        animation: 'modal-fade-in 120ms ease-out',
      }}
    >
        {/* onClick only stops propagation so a click inside the dialog does not
            reach the backdrop's dismiss handler — not a user affordance. */}
        {/* eslint-disable-next-line jsx-a11y/click-events-have-key-events */}
      <div
        role="dialog"
        aria-label="Command palette"
        onClick={(e) => e.stopPropagation()}
        style={{
          width: '600px',
          maxWidth: 'calc(100vw - 32px)',
          maxHeight: '70vh',
          display: 'flex',
          flexDirection: 'column',
          background: 'var(--bg-panel, var(--bg-base))',
          color: 'var(--text-primary)',
          border: '1px solid var(--border)',
          borderRadius: 6,
          boxShadow: '0 12px 48px rgba(0, 0, 0, 0.4)',
          overflow: 'hidden',
        }}
      >
        <input
          ref={inputRef}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Type a command or file path…"
          style={{
            padding: '14px 18px',
            fontSize: 15,
            background: 'transparent',
            color: 'inherit',
            border: 'none',
            borderBottom: '1px solid var(--border)',
            outline: 'none',
            fontFamily: 'inherit',
          }}
        />

        <div style={{ flex: 1, overflowY: 'auto', padding: '6px 0' }}>
          {flat.length === 0 && (
            <div style={{ padding: '20px 18px', color: 'var(--text-muted)', fontSize: 13, fontStyle: 'italic' }}>
              {query ? 'No matches.' : 'Start typing to find commands or files…'}
            </div>
          )}

          {matches.commands.length > 0 && (
            <div>
              <div style={sectionLabelStyle}>Commands</div>
              {matches.commands.map(({ cmd }) => {
                const idx = renderIdx++
                return (
                  <Row
                    key={cmd.id}
                    active={idx === selected}
                    onClick={() => execute(idx)}
                    onMouseEnter={() => setSelected(idx)}
                    title={cmd.title}
                    detail={cmd.section}
                    shortcut={cmd.shortcut}
                  />
                )
              })}
            </div>
          )}

          {matches.files.length > 0 && (
            <div>
              <div style={sectionLabelStyle}>Files</div>
              {matches.files.map(({ path }) => {
                const idx = renderIdx++
                const stem = path.split('/').pop() ?? path
                return (
                  <Row
                    key={path}
                    active={idx === selected}
                    onClick={() => execute(idx)}
                    onMouseEnter={() => setSelected(idx)}
                    title={stem}
                    detail={path}
                  />
                )
              })}
            </div>
          )}
        </div>

        <div style={footerStyle}>
          <span>↑↓ to navigate</span>
          <span>↵ to open</span>
          <span>esc to close</span>
        </div>
      </div>
    </div>,
    document.body,
  )
}

const sectionLabelStyle: React.CSSProperties = {
  padding: '6px 18px',
  fontSize: 10,
  fontFamily: 'var(--font-mono)',
  letterSpacing: '0.08em',
  textTransform: 'uppercase',
  color: 'var(--text-muted)',
}

const footerStyle: React.CSSProperties = {
  padding: '8px 18px',
  borderTop: '1px solid var(--border)',
  fontSize: 10,
  fontFamily: 'var(--font-mono)',
  color: 'var(--text-muted)',
  display: 'flex',
  gap: 16,
  flexShrink: 0,
}

interface RowProps {
  active: boolean
  onClick: () => void
  onMouseEnter: () => void
  title: string
  detail?: string
  shortcut?: string
}

function Row({ active, onClick, onMouseEnter, title, detail, shortcut }: RowProps) {
  return (
    <button
      onClick={onClick}
      onMouseEnter={onMouseEnter}
      style={{
        display: 'flex',
        width: '100%',
        alignItems: 'center',
        padding: '8px 18px',
        background: active ? 'var(--bg-active, var(--bg-base))' : 'transparent',
        color: 'inherit',
        border: 'none',
        cursor: 'pointer',
        fontSize: 13,
        textAlign: 'left',
        gap: 12,
      }}
    >
      <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {title}
      </span>
      {detail && (
        <span
          style={{
            fontSize: 10,
            fontFamily: 'var(--font-mono)',
            color: 'var(--text-muted)',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
            maxWidth: '40%',
          }}
        >
          {detail}
        </span>
      )}
      {shortcut && (
        <span style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--text-muted)' }}>
          {shortcut}
        </span>
      )}
    </button>
  )
}
