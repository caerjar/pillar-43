/**
 * The in-app menu bar — File / View / Go / Tools / Help.
 *
 * Rendered only where there is no native menu. In the macOS app the Tauri
 * shell builds a real menu from the same model
 * (`desktop/src-tauri/src/menu.rs`), so this returns `null` there rather than
 * showing the user two menu bars saying the same thing.
 *
 * Behaviour is assembled from the two dropdown patterns already in the repo
 * rather than invented:
 *
 * - `FileActionsMenu.tsx:19-37` — a `menuRef` plus a `mousedown` listener for
 *   click-outside. No portal: a dropdown anchored to its trigger is not a
 *   modal, and every portal in this codebase is a full-screen backdrop.
 * - `ContextMenu.tsx:26-42` — Escape to close, which FileActionsMenu lacks.
 *
 * ContextMenu also defers its listener attachment by a tick, and that is
 * deliberately NOT copied here. It needs to because it opens from
 * `onContextMenu` (`TreeNodeRow.tsx:572`), so the interaction that opened it is
 * still propagating when the effect runs. This menu opens from `onClick`, which
 * fires only after mousedown has already passed — the document `mousedown`
 * listener attached in the effect cannot see the opening interaction at all.
 *
 * Checked rather than assumed: with the deferral removed, every test here still
 * passed, which is what a guard protecting nothing looks like. The `setTimeout`
 * went with it.
 *
 * Styling reuses `.overflow-menu` from `index.css`, which was orphaned when
 * some earlier left-panel `···` control was removed — no `.tsx` referenced it.
 * It is already tokenised and correct in both themes.
 */
import { useEffect, useRef, useState } from 'react'
import type { MenuAction, MenuDef } from '../../lib/menu/menuModel'
import type { CommandCtx } from '../CommandPalette/commands'
import './MenuBar.css'

export function MenuBar({
  menus,
  ctx,
  hidden,
}: {
  menus: MenuDef[]
  ctx: CommandCtx
  /** True in the native app, where the OS menu is the real one. */
  hidden?: boolean
}) {
  const [openId, setOpenId] = useState<string | null>(null)
  const barRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!openId) return

    function onDown(e: MouseEvent) {
      if (!barRef.current?.contains(e.target as Node)) setOpenId(null)
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpenId(null)
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [openId])

  if (hidden) return null

  function choose(item: MenuAction) {
    setOpenId(null)
    void item.run(ctx)
  }

  return (
    <div className="menubar" ref={barRef} role="menubar">
      {menus.map((menu) => (
        <div key={menu.id} className="menubar__slot">
          <button
            type="button"
            className={`menubar__title${openId === menu.id ? ' menubar__title--open' : ''}`}
            aria-haspopup="menu"
            aria-expanded={openId === menu.id}
            // Hover-to-switch once something is open is the standard menu-bar
            // affordance; without it every menu costs two clicks.
            onMouseEnter={() => openId && setOpenId(menu.id)}
            onClick={() => setOpenId(openId === menu.id ? null : menu.id)}
          >
            {menu.label}
          </button>

          {openId === menu.id && (
            <div className="overflow-menu menubar__dropdown" role="menu" aria-label={menu.label}>
              {menu.items.map((item, i) =>
                item === 'separator' ? (
                  <div key={`sep-${i}`} className="menubar__separator" role="separator" />
                ) : (
                  <button
                    key={item.id}
                    type="button"
                    role="menuitem"
                    className="overflow-menu__item menubar__item"
                    onClick={() => choose(item)}
                  >
                    <span>{item.label}</span>
                    {(item.chord ?? item.accelerator) && (
                      <span className="menubar__accel">
                        {item.chord ?? prettyAccelerator(item.accelerator!)}
                      </span>
                    )}
                  </button>
                ),
              )}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

/**
 * `CmdOrCtrl+Shift+F` → `⌘⇧F`.
 *
 * The model stores Tauri's spelling because the native menu needs it; only
 * this renderer has to make it look like a Mac shortcut.
 */
export function prettyAccelerator(accel: string): string {
  return accel
    .split('+')
    .map((part) => {
      const k = part.trim().toLowerCase()
      if (k === 'cmdorctrl' || k === 'cmd' || k === 'super') return '⌘'
      if (k === 'shift') return '⇧'
      if (k === 'alt' || k === 'option') return '⌥'
      if (k === 'ctrl' || k === 'control') return '⌃'
      return part.trim().toUpperCase()
    })
    .join('')
}
