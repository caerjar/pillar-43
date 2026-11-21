import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { FolderOpen, FileSearch, FileText, Settings, Clock, Users } from 'lucide-react'
import { useAppStore, type LeftTab } from '../stores/appStore'
import { SignOutButton } from './Archive/SignIn/SignOutButton'
import { useWriterRole } from './Archive/Terms/useWriterRole'
import { useSessionStore } from '../stores/sessionStore'

// ── The ribbon ────────────────────────────────────────────────────────────────

// Ask, Explore, People, and Files for an admin alone (see ADMIN_ONLY below),
// then Settings. Each name is written under its icon: no hover to find out
// what a button is, and the same on a phone, which has no hover at all.
const RIBBON: Array<{ id: LeftTab; icon: React.ElementType; label: string }> = [
  { id: 'ask', icon: FileSearch, label: 'Ask' },
  { id: 'explore', icon: Clock, label: 'Explore' },
  { id: 'people', icon: Users, label: 'People' },
  { id: 'files', icon: FolderOpen, label: 'Files' },
]

/** Ribbon entries only an admin is shown. The backend refuses the rest anyway. */
const ADMIN_ONLY: ReadonlySet<LeftTab> = new Set<LeftTab>(['files'])

// A writer's whole ribbon: their own items and the terms on them.
const WRITER_RIBBON: typeof RIBBON = [
  { id: 'terms', icon: FileText, label: 'My work' },
]

export function ActivityBar() {
  const { leftTab, setActivePanel, panelMode, openSettings } = useAppStore()
  const isWriter = useWriterRole()
  const isAdmin = useSessionStore((s) => s.role === 'admin')
  const [hovered, setHovered] = useState<string | null>(null)
  const isFocus = panelMode === 'focus'

  // In focus mode the whole bar hides with the left panel; callers control visibility.
  if (isFocus) return null

  const ribbon = isWriter ? WRITER_RIBBON : RIBBON.filter((p) => isAdmin || !ADMIN_ONLY.has(p.id))

  return (
    <div
      className="activity-bar"
      style={{
        width: 64,
        flexShrink: 0,
        height: '100%',
        backgroundColor: 'var(--bg-panel)',
        borderRight: '1px solid var(--border-subtle)',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        paddingTop: 8,
        paddingBottom: 8,
        gap: 2,
        position: 'relative',
        zIndex: 10,
      }}
    >
      {ribbon.map((p) => (
        <BarIcon
          key={p.id}
          id={p.id}
          icon={p.icon}
          label={p.label}
          active={leftTab === p.id}
          hovered={hovered === p.id}
          onHover={setHovered}
          onClick={() => setActivePanel(p.id)}
        />
      ))}

      {/* Push Settings to the bottom */}
      <div style={{ flex: 1 }} />
      <div style={{ width: 20, height: 1, backgroundColor: 'var(--border-subtle)', margin: '4px 0', flexShrink: 0 }} />

      {/* Settings answers 404 for a writer (org_gate), so they are not offered it. */}
      {!isWriter && (
        <BarIcon
          id="settings"
          icon={Settings}
          label="Settings"
          active={false}
          hovered={hovered === 'settings'}
          onHover={setHovered}
          onClick={() => openSettings()}
        />
      )}
      <SignOutButton />
    </div>
  )
}

// ── Bar icon ─────────────────────────────────────────────────────────────────

interface BarIconProps {
  id: string
  icon: React.ElementType
  label: string
  active: boolean
  hovered: boolean
  onHover: (id: string | null) => void
  onClick: () => void
}

function BarIcon({ id, icon: Icon, label, active, hovered, onHover, onClick }: BarIconProps) {
  return (
    // Hover-only wrapper: it only drives the hover background of the button
    // inside. The button is the control and is reachable by Tab; hover state is
    // decorative and has no keyboard equivalent to add.
    // eslint-disable-next-line jsx-a11y/no-static-element-interactions
    <div
      style={{ position: 'relative', width: 60, flexShrink: 0 }}
      onMouseEnter={() => onHover(id)}
      onMouseLeave={() => onHover(null)}
    >
      {/* Active left-edge amber bar */}
      <AnimatePresence>
        {active && (
          <motion.div
            initial={{ scaleY: 0 }}
            animate={{ scaleY: 1, transition: { duration: 0.15, ease: [0.0, 0.0, 0.2, 1.0] } }}
            exit={{ scaleY: 0, transition: { duration: 0.1, ease: [0.4, 0.0, 1.0, 1.0] } }}
            style={{
              position: 'absolute',
              left: -2,
              top: '50%',
              transform: 'translateY(-50%)',
              width: 2,
              height: 20,
              backgroundColor: 'var(--accent)',
              borderRadius: '0 1px 1px 0',
              transformOrigin: 'center',
            }}
          />
        )}
      </AnimatePresence>

      <button
        onClick={onClick}
        aria-label={label}
        title={label}
        style={{
          width: 60,
          height: 48,
          display: 'flex',
          flexDirection: 'column',
          gap: 2,
          alignItems: 'center',
          justifyContent: 'center',
          background: hovered ? 'var(--bg-hover)' : 'none',
          border: 'none',
          borderRadius: 4,
          fontFamily: 'inherit',
          fontSize: 'var(--text-xs)',
          color: active ? 'var(--accent)' : hovered ? 'var(--text-secondary)' : 'var(--text-muted)',
          transition: 'background 120ms ease, color 120ms ease',
          cursor: 'pointer',
        }}
      >
        <Icon size={16} strokeWidth={1.75} />
        <span style={{ whiteSpace: 'nowrap' }}>{label}</span>
      </button>
    </div>
  )
}
