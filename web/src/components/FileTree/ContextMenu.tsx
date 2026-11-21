/**
 * Right-click context menu component.
 *
 * Positioned popup menu that appears on right-click. Handles keyboard
 * (Escape) and click-outside dismissal. Supports separators, icons,
 * danger styling, disabled items, and hint display.
 */

import { useState, useEffect } from 'react'
import type { ContextMenuItem } from './FileTreeTypes'

export function ContextMenu({
  x,
  y,
  items,
  onClose,
}: {
  x: number
  y: number
  items: Array<ContextMenuItem | 'separator'>
  onClose: () => void
}) {
  const [hint, setHint] = useState<string | null>(null)
  const [hoveredIdx, setHoveredIdx] = useState<number | null>(null)

  useEffect(() => {
    // Delay attaching so the right-click that opened the menu doesn't immediately close it.
    // Listeners are captured outside the timeout so the useEffect cleanup can always remove them.
    const onDown = () => onClose()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    const tid = setTimeout(() => {
      document.addEventListener('mousedown', onDown)
      document.addEventListener('keydown', onKey)
    }, 0)
    return () => {
      clearTimeout(tid)
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [onClose])

  const left = Math.min(x, window.innerWidth - 224)
  const top = Math.min(y, window.innerHeight - 320)

  const menuStyle: React.CSSProperties = {
    position: 'fixed',
    left,
    top,
    background: 'var(--bg-panel)',
    border: '1px solid var(--border)',
    borderRadius: 6,
    boxShadow: '0 6px 24px rgba(0,0,0,0.35)',
    zIndex: 9999,
    minWidth: 210,
    padding: '4px 0',
    fontSize: 13,
  }

  if (hint) {
    return (
      // Stops the mousedown reaching the document listener that dismisses
      // the menu. Not an affordance; the menu items below are the controls.
      // eslint-disable-next-line jsx-a11y/no-static-element-interactions
      <div style={menuStyle} onMouseDown={(e) => e.stopPropagation()}>
        <div
          style={{
            padding: '10px 14px',
            color: 'var(--text-muted)',
            fontSize: 12,
            lineHeight: 1.5,
          }}
        >
          {hint.split('\n').map((line, i) => (
            <div key={i}>{line}</div>
          ))}
        </div>
      </div>
    )
  }

  return (
    // Stops the mousedown reaching the document listener that dismisses
    // the menu. Not an affordance; the menu items below are the controls.
    // eslint-disable-next-line jsx-a11y/no-static-element-interactions
    <div style={menuStyle} onMouseDown={(e) => e.stopPropagation()}>
      {items.map((item, i) =>
        item === 'separator' ? (
          <div
            key={i}
            style={{ height: 1, background: 'var(--border)', margin: '3px 0' }}
          />
        ) : (
          <button
            key={i}
            disabled={item.disabled}
            onClick={(e) => {
              e.stopPropagation()
              item.action()
              if (item.hintAfter) {
                setHint(item.hintAfter)
                setTimeout(onClose, 2200)
              } else {
                onClose()
              }
            }}
            onMouseEnter={() => setHoveredIdx(i)}
            onMouseLeave={() => setHoveredIdx(null)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 9,
              width: '100%',
              padding: '5px 14px',
              background:
                hoveredIdx === i && !item.disabled
                  ? 'var(--bg-hover)'
                  : 'transparent',
              border: 'none',
              color: item.danger
                ? 'var(--error)'
                : item.disabled
                  ? 'var(--text-muted)'
                  : 'var(--text-primary)',
              cursor: item.disabled ? 'default' : 'pointer',
              textAlign: 'left',
              fontSize: 13,
              opacity: item.disabled ? 0.45 : 1,
              fontFamily: 'inherit',
            }}
          >
            <span
              style={{
                width: 16,
                textAlign: 'center',
                fontSize: 11,
                color: item.danger ? 'var(--error)' : 'var(--text-muted)',
                flexShrink: 0,
              }}
            >
              {item.icon}
            </span>
            {item.label}
          </button>
        )
      )}
    </div>
  )
}
