import { useEffect } from 'react'

/**
 * Combo string format:
 *   "mod+k"     — ⌘K on Mac, Ctrl+K elsewhere (matches event.metaKey || event.ctrlKey)
 *   "mod+shift+f" — ⌘⇧F / Ctrl+Shift+F
 *   "mod+["
 *   "j"         — bare letter (no modifier; ignored when typing in inputs)
 *   "?"         — printable character
 *   "Escape"    — KeyboardEvent.key value directly
 *   "g g"       — chord: two `g` presses in <500ms
 *
 * Handlers fire when no modifier-required event is currently focused on a
 * text input (input/textarea/contenteditable), unless the binding includes
 * a modifier (mod/shift/alt) — those always fire.
 */
export type KeyHandler = (e: KeyboardEvent) => void

export interface KeyBindings {
  [combo: string]: KeyHandler
}

const CHORD_TIMEOUT_MS = 500

function isTextInput(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  if (target.isContentEditable) return true
  const tag = target.tagName
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT'
}

function comboMatches(combo: string, e: KeyboardEvent): boolean {
  const parts = combo.toLowerCase().split('+').map((p) => p.trim())
  const wantMod = parts.includes('mod')
  const wantShift = parts.includes('shift')
  const wantAlt = parts.includes('alt')
  const key = parts[parts.length - 1]
  const hasMod = e.metaKey || e.ctrlKey

  if (wantMod !== hasMod) return false
  // Shift is inherent to typing a punctuation char like "?" (shift+/), so don't
  // require the combo to declare it for those. For letters/digits/named keys,
  // shift is a real distinguisher (k vs shift+k) and must match.
  const keyIsPunct = key.length === 1 && !/[a-z0-9]/.test(key)
  if (!keyIsPunct && wantShift !== e.shiftKey) return false
  if (wantAlt !== e.altKey) return false

  // Compare against e.key, lowercased. Specials: Escape, Enter, ArrowUp, etc.
  // For printable keys event.key is the unmodified character.
  return e.key.toLowerCase() === key
}

/**
 * Register a map of keyboard bindings for the app.
 *
 *   useGlobalKeyboard({
 *     'mod+k':       (e) => { e.preventDefault(); openSearch() },
 *     'mod+p':       (e) => { e.preventDefault(); openCommandPalette() },
 *     'Escape':      ()  => closePalette(),
 *     'g g':         ()  => scrollToTop(),
 *   })
 *
 * Bindings without `mod`/`shift`/`alt` are ignored when a text input has focus.
 * Each call replaces the previous bindings for the same component instance.
 */
export function useGlobalKeyboard(bindings: KeyBindings, enabled = true) {
  useEffect(() => {
    if (!enabled) return

    let chord: string | null = null
    let chordTimer: ReturnType<typeof setTimeout> | null = null

    const onKey = (e: KeyboardEvent) => {
      const inText = isTextInput(e.target)

      // First, try exact-combo bindings (single-key with modifiers, or named keys)
      for (const combo of Object.keys(bindings)) {
        if (combo.includes(' ')) continue // chord, handled below
        const isPlain = !combo.toLowerCase().match(/(mod|shift|alt)/)
        if (isPlain && inText && combo !== 'Escape') continue
        if (comboMatches(combo, e)) {
          bindings[combo](e)
          return
        }
      }

      // Chord bindings (e.g. "g g")
      if (inText) return
      const chordCandidates = Object.keys(bindings).filter((c) => c.includes(' '))
      if (chordCandidates.length === 0) return

      const k = e.key.toLowerCase()
      // No modifiers allowed in chord prefix
      if (e.metaKey || e.ctrlKey || e.altKey) return

      if (chord) {
        const candidate = `${chord} ${k}`
        const handler = bindings[candidate]
        chord = null
        if (chordTimer) {
          clearTimeout(chordTimer)
          chordTimer = null
        }
        if (handler) {
          handler(e)
          return
        }
      }

      // Maybe start a chord
      if (chordCandidates.some((c) => c.startsWith(`${k} `))) {
        chord = k
        if (chordTimer) clearTimeout(chordTimer)
        chordTimer = setTimeout(() => {
          chord = null
          chordTimer = null
        }, CHORD_TIMEOUT_MS)
      }
    }

    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('keydown', onKey)
      if (chordTimer) clearTimeout(chordTimer)
    }
  }, [bindings, enabled])
}
