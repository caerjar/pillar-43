import { useCallback, useRef } from 'react'

/** px per arrow press, and per Shift+arrow press. */
const STEP_SMALL = 16
const STEP_LARGE = 64

interface ResizeHandleProps {
  onResize: (width: number) => void
  minWidth?: number
  maxWidth?: number
}

export function ResizeHandle({ onResize, minWidth = 220, maxWidth = 520 }: ResizeHandleProps) {
  const dragging = useRef(false)
  const startX = useRef(0)
  const startWidth = useRef(0)

  const onMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    dragging.current = true
    startX.current = e.clientX
    startWidth.current = (e.currentTarget.parentElement?.offsetWidth ?? 280)

    const onMouseMove = (ev: MouseEvent) => {
      if (!dragging.current) return
      const delta = ev.clientX - startX.current
      const next = Math.min(maxWidth, Math.max(minWidth, startWidth.current + delta))
      onResize(next)
    }

    const onMouseUp = () => {
      dragging.current = false
      window.removeEventListener('mousemove', onMouseMove)
      window.removeEventListener('mouseup', onMouseUp)
    }

    window.addEventListener('mousemove', onMouseMove)
    window.addEventListener('mouseup', onMouseUp)
  }, [onResize, minWidth, maxWidth])

  // Keyboard resizing. The handle was drag-only, so a keyboard user could not
  // resize the panel at all — the lint finding here was a real capability gap,
  // not a missing attribute. Arrow keys nudge, Shift+Arrow jumps, Home/End go
  // to the limits; the same convention as a native slider.
  const onKeyDown = useCallback((e: React.KeyboardEvent<HTMLDivElement>) => {
    const width = e.currentTarget.parentElement?.offsetWidth ?? minWidth
    const step = e.shiftKey ? STEP_LARGE : STEP_SMALL
    let next: number | null = null
    if (e.key === 'ArrowLeft') next = width - step
    else if (e.key === 'ArrowRight') next = width + step
    else if (e.key === 'Home') next = minWidth
    else if (e.key === 'End') next = maxWidth
    if (next === null) return
    e.preventDefault()
    onResize(Math.min(maxWidth, Math.max(minWidth, next)))
  }, [onResize, minWidth, maxWidth])

  return (
    <div
      onMouseDown={onMouseDown}
      onKeyDown={onKeyDown}
      // separator with aria-orientation is the role for a draggable splitter;
      // it becomes focusable precisely because it is operable.
      role="separator"
      aria-orientation="vertical"
      aria-label="Resize panel"
      tabIndex={0}
      style={{
        position: 'absolute',
        top: 0,
        right: -2,
        width: 4,
        height: '100%',
        cursor: 'col-resize',
        zIndex: 10,
      }}
    />
  )
}
