import { useState, useRef, useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api } from '../../lib/api'
import { useAppStore } from '../../stores/appStore'
import { speechRecognitionSupported, createContinuous } from '../../lib/speech'
import { errorMessage } from '../../lib/errors'

type State = 'idle' | 'listening' | 'paused'

export function Transcribe() {
  const setCurrentFile = useAppStore((s) => s.setCurrentFile)
  const qc = useQueryClient()
  const [recState, setRecState] = useState<State>('idle')
  const [transcript, setTranscript] = useState('')
  const [interim, setInterim] = useState('')
  const [savePath, setSavePath] = useState('notes/transcripts/')
  // Day 1 polish — voice→Inbox routing. Toggle the default save path
  // between transcripts/ (default, treats it as a personal note) and
  // inbox/ (lets the existing inbox processor classify + suggest a thread).
  const [routeToInbox, setRouteToInbox] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [sttLang, setSttLang] = useState('')

  const recRef = useRef<SpeechRecognition | null>(null)
  const transcriptRef = useRef('')
  const bottomRef = useRef<HTMLDivElement>(null)

  // Load default voice language from settings
  useEffect(() => {
    api.appSettings().then((s) => {
      if (s.voice_language) setSttLang(s.voice_language)
    }).catch(() => {})
  }, [])

  // Keep ref in sync so callbacks always have latest value
  useEffect(() => { transcriptRef.current = transcript }, [transcript])

  // Auto-scroll as transcript grows
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [transcript, interim])

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      recRef.current?.stop()
      recRef.current = null
    }
  }, [])

  function startListening() {
    setError('')
    const rec = createContinuous({
      onInterim: (t) => setInterim(t),
      onFinal: (t) => {
        setTranscript((prev) => {
          const sep = prev && !prev.endsWith('\n') ? ' ' : ''
          return prev + sep + t
        })
        setInterim('')
      },
      onEnd: () => {
        setInterim('')
        // If we're still supposed to be listening, restart (browser ends session
        // after ~60s of silence on some engines)
        if (recRef.current) {
          try { recRef.current.start() } catch { /* already stopped */ }
        }
      },
      onError: (msg) => {
        if (msg === 'no-speech') return  // ignore silence
        setError(`Mic error: ${msg}`)
        setRecState('idle')
        recRef.current = null
      },
    }, { lang: sttLang || undefined })
    if (!rec) {
      setError('Speech recognition not supported in this browser.')
      return
    }
    recRef.current = rec
    rec.start()
    setRecState('listening')
  }

  function pause() {
    if (!recRef.current) return
    recRef.current.stop()
    // Don't null out recRef — we'll restart on resume
    setRecState('paused')
    setInterim('')
  }

  function resume() {
    if (!recRef.current) return
    try { recRef.current.start() } catch { /* ignore */ }
    setRecState('listening')
  }

  function stop() {
    recRef.current?.stop()
    recRef.current = null
    setRecState('idle')
    setInterim('')
  }

  function clear() {
    stop()
    setTranscript('')
    setInterim('')
    setError('')
  }

  async function saveToFile() {
    const text = transcript.trim()
    const path = savePath.trim()
    if (!text || !path) return

    // Auto-append filename if path ends with /
    const finalPath = path.endsWith('/')
      ? path + new Date().toISOString().slice(0, 19).replace('T', '-').replace(/:/g, '') + '.md'
      : path

    setSaving(true)
    try {
      const header = `# Transcript — ${new Date().toLocaleString()}\n\n`
      await api.writeFile(finalPath, header + text)
      qc.invalidateQueries({ queryKey: ['tree'] })
      setCurrentFile(finalPath)
      setTranscript('')
    } catch (e) {
      setError(`Save failed: ${errorMessage(e)}`)
    } finally {
      setSaving(false)
    }
  }

  if (!speechRecognitionSupported) {
    return (
      <div style={{ padding: 24, color: 'var(--text-muted)', fontSize: 13, lineHeight: 1.6 }}>
        <div style={{ marginBottom: 8, color: 'var(--text-primary)', fontWeight: 600 }}>
          Transcription Mode
        </div>
        Speech recognition is not supported in this browser.
        Use Chrome, Edge, or Safari for voice features.
      </div>
    )
  }

  const hasText = transcript.trim().length > 0

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>

      {/* Header */}
      <div style={{
        padding: '10px 14px',
        borderBottom: '1px solid var(--border)',
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        flexShrink: 0,
      }}>
        <span style={{ flex: 1, fontWeight: 600, fontSize: 12, color: 'var(--text-primary)' }}>
          Transcription
        </span>
        {recState === 'listening' && (
          <span style={{
            fontSize: 10,
            color: 'var(--error)',
            display: 'flex',
            alignItems: 'center',
            gap: 4,
          }}>
            <span style={{ animation: 'pulse 1.2s ease-in-out infinite', display: 'inline-block' }}>⏺</span>
            LIVE
          </span>
        )}
        {recState === 'paused' && (
          <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>⏸ PAUSED</span>
        )}
      </div>

      {/* Transcript area */}
      <div style={{
        flex: 1,
        overflow: 'auto',
        padding: '16px 14px',
        fontFamily: 'var(--font-mono)',
        fontSize: 13,
        lineHeight: 1.7,
        color: 'var(--text-secondary)',
        whiteSpace: 'pre-wrap',
        wordBreak: 'break-word',
      }}>
        {transcript}
        {interim && (
          <span style={{ color: 'var(--text-muted)', fontStyle: 'italic' }}>{interim}</span>
        )}
        {!transcript && !interim && (
          <span style={{ color: 'var(--text-muted)', fontStyle: 'italic' }}>
            {recState === 'idle'
              ? 'Press Start to begin dictating…'
              : recState === 'paused'
              ? 'Paused. Press Resume to continue.'
              : 'Listening…'}
          </span>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Error */}
      {error && (
        <div style={{
          padding: '6px 14px',
          fontSize: 11,
          color: 'var(--error)',
          fontFamily: 'var(--font-mono)',
          borderTop: '1px solid var(--border)',
          flexShrink: 0,
        }}>
          {error}
        </div>
      )}

      {/* Controls */}
      <div style={{
        padding: '10px 14px',
        borderTop: '1px solid var(--border)',
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
        flexShrink: 0,
      }}>

        {/* Language selector */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ fontSize: 10, color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>Lang:</span>
          <input
            value={sttLang}
            onChange={(e) => setSttLang(e.target.value)}
            placeholder="e.g. en-US, fr, es"
            disabled={recState !== 'idle'}
            title="Recognition language (BCP-47). Leave blank for browser default."
            style={{
              flex: 1,
              background: 'var(--bg-base)',
              color: 'var(--text-secondary)',
              border: '1px solid var(--border)',
              borderRadius: 3,
              padding: '3px 6px',
              fontSize: 10,
              fontFamily: 'var(--font-mono)',
              opacity: recState !== 'idle' ? 0.5 : 1,
            }}
          />
        </div>

        {/* Record controls */}
        <div style={{ display: 'flex', gap: 6 }}>
          {recState === 'idle' && (
            <button onClick={startListening} style={btnStyle('accent')}>
              ⏺ Start
            </button>
          )}
          {recState === 'listening' && (
            <>
              <button onClick={pause} style={btnStyle('muted')}>
                ⏸ Pause
              </button>
              <button onClick={stop} style={btnStyle('danger')}>
                ⏹ Stop
              </button>
            </>
          )}
          {recState === 'paused' && (
            <>
              <button onClick={resume} style={btnStyle('accent')}>
                ▶ Resume
              </button>
              <button onClick={stop} style={btnStyle('muted')}>
                ⏹ Stop
              </button>
            </>
          )}
          {hasText && (
            <button onClick={clear} style={{ ...btnStyle('muted'), marginLeft: 'auto' }}>
              Clear
            </button>
          )}
        </div>

        {/* Save controls */}
        {hasText && (
          <>
            <label
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 6,
                fontSize: 10,
                fontFamily: 'var(--font-mono)',
                color: 'var(--text-muted)',
                cursor: 'pointer',
              }}
              title="When on, save to notes/inbox/ so the inbox processor classifies + suggests a thread"
            >
              <input
                type="checkbox"
                checked={routeToInbox}
                onChange={(e) => {
                  const on = e.target.checked
                  setRouteToInbox(on)
                  // Toggle the default save path. User can still type to override
                  // either way; toggling resets to the new default.
                  setSavePath(on ? 'notes/inbox/' : 'notes/transcripts/')
                }}
                style={{ cursor: 'pointer' }}
              />
              Route to Inbox (auto-classify)
            </label>
            <div style={{ display: 'flex', gap: 6 }}>
              <input
                value={savePath}
                onChange={(e) => setSavePath(e.target.value)}
                placeholder={routeToInbox ? 'notes/inbox/note.md' : 'notes/transcripts/note.md'}
                style={{
                  flex: 1,
                  background: 'var(--bg-base)',
                  color: 'var(--text-secondary)',
                  border: '1px solid var(--border)',
                  borderRadius: 3,
                  padding: '3px 6px',
                  fontSize: 10,
                  fontFamily: 'var(--font-mono)',
                  minWidth: 0,
                }}
              />
              <button
                onClick={saveToFile}
                disabled={saving || !savePath.trim()}
                style={{
                  ...btnStyle('muted'),
                  opacity: saving || !savePath.trim() ? 0.5 : 1,
                  flexShrink: 0,
                }}
              >
                {routeToInbox ? 'Save to Inbox' : 'Save to File'}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

function btnStyle(variant: 'accent' | 'muted' | 'danger'): React.CSSProperties {
  const colors = {
    accent: { bg: 'var(--accent)', color: 'var(--on-accent)', border: 'none' },
    muted: { bg: 'transparent', color: 'var(--text-secondary)', border: '1px solid var(--border)' },
    danger: {
      bg: 'transparent',
      color: 'var(--error)',
      border: '1px solid var(--error)',
    },
  }
  const c = colors[variant]
  return {
    padding: '4px 12px',
    background: c.bg,
    color: c.color,
    border: c.border,
    borderRadius: 4,
    cursor: 'pointer',
    fontSize: 11,
  }
}
