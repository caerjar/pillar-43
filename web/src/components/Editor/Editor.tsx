import { useState, useEffect, useRef, useCallback, useMemo, lazy, Suspense, Component } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import CodeMirror, { type ReactCodeMirrorRef } from '@uiw/react-codemirror'
import { markdown } from '@codemirror/lang-markdown'
import { oneDark } from '@codemirror/theme-one-dark'
import { EditorView } from '@codemirror/view'
import { api, type FileContent } from '../../lib/api'
import { AUDIO_EXTS, IMAGE_VIEWER_EXTS, VIDEO_EXTS } from '../../lib/multimediaExts'
import { renderMarkdown } from '../../lib/markdown'
import { splitFrontmatter } from '../../lib/frontmatter'
import { useAppStore } from '../../stores/appStore'
import { speechSynthesisSupported, speak, loadVoices } from '../../lib/speech'
import { STALE_TIME } from '../../constants'
import { errorMessage } from '../../lib/errors'

const PDFViewer = lazy(() =>
  import('./PDFViewer').then((m) => ({ default: m.PDFViewer }))
)

class PDFErrorBoundary extends Component<
  { rawUrl: string; children: React.ReactNode },
  { crashed: boolean }
> {
  state = { crashed: false }
  static getDerivedStateFromError() { return { crashed: true } }
  render() {
    if (this.state.crashed)
      return <iframe src={this.props.rawUrl} style={{ width: '100%', height: '100%', border: 'none' }} />
    return this.props.children
  }
}

/**
 * The paper sheet a rendered preview sits on.
 *
 * Deliberately NOT a design token and deliberately not theme-reactive: SVG and
 * HTML are both authored against a white page, so a document that declares no
 * background of its own renders dark-on-dark over `--bg-base`. A token would
 * follow the theme and reintroduce exactly that. Named here rather than inline
 * for the reason `PDFViewer` names its tray — see the maintainer notes § "Colours go
 * through design tokens" for the three standing exceptions.
 */
const PREVIEW_PAPER = '#fff'

export function Editor() {
  const currentFile = useAppStore((s) => s.currentFile)
  const setCurrentFile = useAppStore((s) => s.setCurrentFile)
  const pdfTarget = useAppStore((s) => s.pdfTarget)
  const panelMode = useAppStore((s) => s.panelMode)
  const history = useAppStore((s) => s.history)
  const historyIndex = useAppStore((s) => s.historyIndex)
  const goBack = useAppStore((s) => s.goBack)
  const goForward = useAppStore((s) => s.goForward)
  const pendingEdit = useAppStore((s) => s.pendingEdit)
  const setPendingEdit = useAppStore((s) => s.setPendingEdit)
  const pendingLine = useAppStore((s) => s.pendingLine)
  const setPendingLine = useAppStore((s) => s.setPendingLine)
  const [editMode, setEditMode] = useState(false)
  const [draft, setDraft] = useState('')
  const [dirty, setDirty] = useState(false)
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')
  const [saveError, setSaveError] = useState<string | null>(null)
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const cmRef = useRef<ReactCodeMirrorRef | null>(null)
  // Latest-value refs — every save path reads from these instead of closing
  // over React state. This eliminates a class of stale-closure bugs where the
  // 700ms debounce timer (or ⌘S handler) fires with stale path/draft after
  // navigation, re-render, or mutation completion.
  const draftRef = useRef(draft)
  const dirtyRef = useRef(dirty)
  const currentFileRef = useRef(currentFile)
  const [transcribing, setTranscribing] = useState<{ stage: string; fraction: number } | null>(null)
  const [speaking, setSpeaking] = useState(false)
  const stopSpeakRef = useRef<(() => void) | null>(null)
  const [voices, setVoices] = useState<SpeechSynthesisVoice[]>([])
  const [selectedVoiceURI, setSelectedVoiceURI] = useState<string>('')
  const qc = useQueryClient()

  // Stable reference for CodeMirror — re-creating the extensions array on
  // every parent render makes CodeMirror reconfigure itself on every render,
  // which on a fast typer compounds into perceptible lag / "becomes
  // unresponsive". Memoize once so the prop reference never changes
  // (the maintainer notes "Editor freeze symptom").
  const cmExtensions = useMemo(
    () => [markdown()],
    [],
  )

  // The editor follows the app's theme. It was pinned to `oneDark` regardless,
  // so light mode left a dark slab in the one pane you look at most.
  //
  // Both branches are reference-stable — `oneDark` is a module constant and
  // `'light'` a string literal — so this changes identity only when the theme
  // actually changes, which is the one moment CodeMirror *should* reconfigure.
  // A value built inline here (an object literal, an EditorView.theme() call)
  // would be a fresh reference every render and reconfigure on each one: the
  // same shape as the freeze documented above.
  const lightMode = useAppStore((s) => s.lightMode)
  const cmTheme = lightMode ? 'light' : oneDark

  // Stream a Whisper / vision transcription. Updates the inline progress chip
  // in the binary toolbar; on completion, navigates to the transcript .md so
  // the user immediately sees the result.
  const startTranscription = async () => {
    if (!currentFile) return
    setTranscribing({ stage: 'starting', fraction: 0 })
    try {
      const res = await api.transcribe(currentFile)
      if (!res.body) throw new Error('No SSE body')
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buf = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        const lines = buf.split('\n')
        buf = lines.pop() ?? ''
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const payload = line.slice(6).trim()
          if (payload === '[DONE]') continue
          try {
            const evt = JSON.parse(payload)
            if (evt.event === 'progress') {
              setTranscribing({ stage: evt.stage, fraction: evt.fraction })
            } else if (evt.event === 'done') {
              setTranscribing(null)
              setCurrentFile(evt.transcript_path)
              return
            } else if (evt.event === 'error') {
              setTranscribing({ stage: `error: ${evt.message}`, fraction: 0 })
              setTimeout(() => setTranscribing(null), 5000)
              return
            }
          } catch {
            /* non-JSON keepalive line */
          }
        }
      }
    } catch (e) {
      setTranscribing({ stage: `error: ${errorMessage(e)}`, fraction: 0 })
      setTimeout(() => setTranscribing(null), 5000)
    }
  }

  const { data, isLoading } = useQuery({
    queryKey: ['file', currentFile],
    queryFn: () => api.readFile(currentFile!),
    enabled: !!currentFile,
    staleTime: STALE_TIME.STATIC,
  })

  // Frontmatter, split off for display. `marked` rendered the opening `---` as
  // a horizontal rule and the keys as one run-on paragraph, so every note
  // carrying metadata opened with a slab of visible garbage. Memoised because
  // view mode re-renders on unrelated store writes and this walks the source.
  //
  // Edit mode deliberately still shows the raw block: that is where you change
  // it, and hiding it there would make the properties uneditable.
  const viewSource = draft || data?.content || ''
  const { body: viewBody } = useMemo(
    () => splitFrontmatter(viewSource),
    [viewSource],
  )

  const docExts = ['.epub', '.docx', '.mobi', '.pages', '.key', '.numbers']
  const needsText = !!(data?.binary && docExts.includes(data.ext ?? ''))
  const { data: textData, isLoading: textLoading } = useQuery({
    queryKey: ['file-text', currentFile],
    queryFn: () => api.fileText(currentFile!),
    enabled: needsText,
  })

  useEffect(() => {
    // Don't clobber in-progress edits if a stale `data` callback fires
    // while the user is mid-keystroke (e.g. an unrelated query update).
    // Initial load works because dirtyRef starts false.
    // `too_large` also guards here, not only at render: the payload carries
    // binary:false with a null body, so without it draft would be seeded to ''
    // — one stale render away from being flushed over the real file.
    if (data && !data.binary && !data.too_large && !dirtyRef.current) {
      setDraft(data.content ?? '')
      setDirty(false)
      setSaveStatus('idle')
      setSaveError(null)
    }
  }, [data])

  // Keep the latest-value refs in sync. Cheap, runs on every relevant state change.
  useEffect(() => { draftRef.current = draft }, [draft])
  useEffect(() => { dirtyRef.current = dirty }, [dirty])
  useEffect(() => { currentFileRef.current = currentFile }, [currentFile])

  // Reset to view mode when navigating to a different file. The
  // pendingEdit effect below re-enters edit mode for + New.
  useEffect(() => { setEditMode(false) }, [currentFile])

  // Auto-enter edit mode when a new note is created via + New
  useEffect(() => {
    if (pendingEdit) {
      setEditMode(true)
      setPendingEdit(false)
    }
  }, [pendingEdit, setPendingEdit])

  // Scroll to a specific line when a navigation source set pendingLine
  // (anti-search ghost click, file-result line, future deep links).
  // Consumed once and cleared. Waits for `data` so CodeMirror is mounted
  // with content before we call coordsAtPos / scrollIntoView.
  useEffect(() => {
    if (pendingLine == null) return
    if (!data || data.binary) return
    const view = cmRef.current?.view
    if (!view) return
    const totalLines = view.state.doc.lines
    const line = Math.max(1, Math.min(pendingLine, totalLines))
    const linePos = view.state.doc.line(line).from
    view.dispatch({
      selection: { anchor: linePos },
      effects: EditorView.scrollIntoView(linePos, { y: 'center' }),
    })
    setPendingLine(null)
  }, [pendingLine, data, setPendingLine])

  // Load TTS voices and pre-select based on default voice_language setting
  useEffect(() => {
    const cleanup = loadVoices((v) => {
      setVoices(v)
      // Pre-select a voice matching the default language if not already chosen
      api.appSettings().then((s) => {
        if (s.voice_language && !selectedVoiceURI) {
          const lang = s.voice_language.toLowerCase()
          const match = v.find((voice) => voice.lang.toLowerCase().startsWith(lang))
          if (match) setSelectedVoiceURI(match.voiceURI)
        }
      }).catch((e) => console.error('voice setup failed', e))
    })
    return cleanup
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // Stop reading aloud when the file changes
  useEffect(() => {
    return () => {
      stopSpeakRef.current?.()
      setSpeaking(false)
    }
  }, [currentFile])

  const toggleRead = () => {
    if (speaking) {
      stopSpeakRef.current?.()
      setSpeaking(false)
      return
    }
    const text = draft || data?.content || ''
    if (!text.trim()) return
    setSpeaking(true)
    const selectedVoice = voices.find((v) => v.voiceURI === selectedVoiceURI) ?? null
    stopSpeakRef.current = speak(text, () => setSpeaking(false), {
      voice: selectedVoice,
      lang: selectedVoice?.lang,
    })
  }

  // Save mutation — takes path + content as args so the request is bound to
  // the values at call time, not whatever's in scope when the closure was
  // created. Eliminates wrong-file invalidation if the user navigates while
  // a save is in flight.
  const saveMutation = useMutation({
    mutationFn: async ({ path, content }: { path: string; content: string }) => {
      const target = path.includes('.') ? path : path + '.md'
      await api.writeFile(target, content)
      return { originalPath: path, savedTo: target, content }
    },
    onMutate: () => {
      setSaveStatus('saving')
      setSaveError(null)
    },
    onSuccess: ({ originalPath, savedTo, content }) => {
      // Only adopt the .md-appended path if the user is still on the file we saved.
      if (currentFileRef.current === originalPath && originalPath !== savedTo) {
        setCurrentFile(savedTo)
      }
      // Compare against ref, not closed-over state, so a concurrent navigation
      // doesn't make us mark the wrong file clean.
      if (currentFileRef.current === originalPath || currentFileRef.current === savedTo) {
        setDirty(false)
      }
      setSaveStatus('saved')
      // Update the cache with the content we just wrote — no refetch.
      // A refetch here races with keystrokes typed during the round-trip:
      // when the stale GET resolves, the data-sync effect would overwrite
      // the in-progress draft with the older saved content.
      qc.setQueryData<FileContent>(['file', savedTo], (old) =>
        old ? { ...old, content } : old
      )
      // Saving a brand-new path adds a tree node — refresh so it shows up
      // immediately instead of waiting for the 30s staleTime / a focus refetch.
      qc.invalidateQueries({ queryKey: ['tree'] })
    },
    onError: (err) => {
      setSaveStatus('error')
      setSaveError(err instanceof Error ? err.message : 'Save failed')
    },
  })

  // flush() — single source of truth for triggering a save. Reads from refs,
  // never from closure-captured state. All save callers (700ms debounce timer,
  // ⌘S handler, manual Save button, file-change cleanup) go through this.
  //
  // Stability matters here. Earlier this used `useCallback(..., [saveMutation])`
  // — but `saveMutation` is a fresh object on every render (status changes,
  // internal counters), so flush got a new identity every render, which made
  // every effect that depended on flush re-run. The file-change-cleanup effect
  // at "[currentFile, flush]" then ran its cleanup() — which IS flush() — on
  // every keystroke, firing a save per character and grinding the editor.
  //
  // Fix: stash the latest mutate function in a ref. flush itself is stable
  // (empty deps), and the cleanup/keydown effects only depend on currentFile.
  const mutateRef = useRef(saveMutation.mutate)
  useEffect(() => { mutateRef.current = saveMutation.mutate }, [saveMutation.mutate])

  const flush = useCallback(() => {
    if (saveTimerRef.current) {
      clearTimeout(saveTimerRef.current)
      saveTimerRef.current = null
    }
    const path = currentFileRef.current
    if (!path || !dirtyRef.current) return
    mutateRef.current({ path, content: draftRef.current })
  }, [])

  // Flush any pending edit BEFORE leaving the file, so navigation doesn't
  // silently drop the last keystrokes.
  useEffect(() => {
    return () => { flush() }
  }, [currentFile, flush])

  // (Removed: the previous 30s autosave useEffect was dead code — `draft` in
  // its deps reset the timer on every keystroke, and `saveMutation` was
  // missing with eslint-disable. The 700ms onChange debounce + flush-on-switch
  // + ⌘S + Save button cover every save path.)

  if (!currentFile) {
    return (
      <div
        style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}
        data-testid="editor-empty"
      >
        <div style={{
          padding: '20px 24px 12px',
          color: 'var(--text-muted)',
          fontSize: 12,
          borderBottom: '1px solid var(--border-subtle)',
          flexShrink: 0,
        }}>
          Open a file from the panel on the left, or press <kbd style={{ background: 'var(--bg-active)', border: '1px solid var(--border)', borderRadius: 3, padding: '1px 5px', fontSize: 11 }}>⌘K</kbd> to find one.
        </div>
      </div>
    )
  }

  // Fix 1: subtle loading state instead of blank space
  if (isLoading) {
    return (
      <div style={{ color: 'var(--text-muted)', fontSize: 12, padding: 16 }} data-testid="editor-loading">Loading…</div>
    )
  }

  // Must precede the `binary` branch: the backend sends `binary: false` with a
  // null body for oversized text, so this file would otherwise fall through to
  // the editor, mount CodeMirror with '', and let autosave truncate it.
  if (data?.too_large) {
    return (
      <div
        data-testid="editor-too-large"
        style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 32 }}
      >
        <div style={{ maxWidth: 460, textAlign: 'center', color: 'var(--text-muted)', fontSize: 13, lineHeight: 1.6 }}>
          <div style={{ fontSize: 15, color: 'var(--text-primary)', marginBottom: 8 }}>Too large to edit</div>
          <div>{data.message ?? `This file is ${data.size_mb ?? '?'} MB.`}</div>
          <div style={{ marginTop: 12 }}>
            <a href={`/api/file/raw?path=${encodeURIComponent(currentFile!)}`} target="_blank" rel="noreferrer">
              Open raw ↗
            </a>
          </div>
        </div>
      </div>
    )
  }

  if (data?.binary) {
    const ext = data.ext?.replace('.', '').toUpperCase() ?? 'binary'
    const rawUrl = `/api/file/raw?path=${encodeURIComponent(currentFile!)}`
    const isImage = (IMAGE_VIEWER_EXTS as readonly string[]).includes(data.ext ?? '')
    const isAudio = (AUDIO_EXTS as readonly string[]).includes(data.ext ?? '')
    const isVideo = (VIDEO_EXTS as readonly string[]).includes(data.ext ?? '')
    const isPDF = data.ext === '.pdf'
    const isDoc = docExts.includes(data.ext ?? '')

    return (
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }} data-testid="editor-binary">
        {/* Toolbar */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 16px', borderBottom: '1px solid var(--border)', background: 'var(--bg-panel)', flexShrink: 0 }}>
          <button
            onClick={goBack}
            disabled={historyIndex <= 0}
            title="Back (⌘[)"
            style={{ padding: '2px 7px', background: 'transparent', color: historyIndex <= 0 ? 'var(--text-muted)' : 'var(--text-secondary)', border: '1px solid var(--border)', borderRadius: 3, cursor: historyIndex <= 0 ? 'default' : 'pointer', fontSize: 12, opacity: historyIndex <= 0 ? 0.4 : 1 }}
          >←</button>
          <button
            onClick={goForward}
            disabled={historyIndex >= history.length - 1}
            title="Forward (⌘])"
            style={{ padding: '2px 7px', background: 'transparent', color: historyIndex >= history.length - 1 ? 'var(--text-muted)' : 'var(--text-secondary)', border: '1px solid var(--border)', borderRadius: 3, cursor: historyIndex >= history.length - 1 ? 'default' : 'pointer', fontSize: 12, opacity: historyIndex >= history.length - 1 ? 0.4 : 1 }}
          >→</button>
          <span style={{ flex: 1, color: 'var(--text-muted)', fontSize: 12, fontFamily: 'var(--font-mono)' }}>
            {currentFile}
          </span>
          <span style={{ fontSize: 11, color: 'var(--text-muted)', background: 'var(--bg-active)', border: '1px solid var(--border)', borderRadius: 3, padding: '1px 6px' }}>
            {ext}
          </span>
          <a
            href={rawUrl}
            target="_blank"
            rel="noopener noreferrer"
            style={{ fontSize: 11, color: 'var(--text-muted)', textDecoration: 'none', border: '1px solid var(--border)', borderRadius: 3, padding: '1px 6px' }}
          >
            Open ↗
          </a>
          {(isImage || isAudio || isVideo) && (
            <button
              onClick={startTranscription}
              disabled={!!transcribing}
              title={isImage ? "Caption this image with the local vision model" : "Transcribe audio (and sample video frames)"}
              style={{
                padding: '1px 6px',
                background: transcribing ? 'var(--accent-dim)' : 'transparent',
                color: transcribing ? 'var(--accent)' : 'var(--text-muted)',
                border: '1px solid var(--border)',
                borderRadius: 3,
                cursor: transcribing ? 'progress' : 'pointer',
                fontSize: 11,
                whiteSpace: 'nowrap',
                maxWidth: 280,
                overflow: 'hidden',
                textOverflow: 'ellipsis',
              }}
            >
              {transcribing
                ? `${Math.round(transcribing.fraction * 100)}% — ${transcribing.stage}`
                : 'Transcribe'}
            </button>
          )}
        </div>

        {/* Content */}
        {isPDF && pdfTarget && pdfTarget.path === currentFile && pdfTarget.text && (
          <div
            data-testid="pdf-cited"
            style={{
              padding: '6px 12px', borderLeft: '2px solid var(--accent)', margin: '0 0 0 12px',
              color: 'var(--text-muted)', fontSize: 'var(--text-sm)', lineHeight: 1.45,
              display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden',
            }}
          >
            Cited: {pdfTarget.text}
          </div>
        )}
        {isPDF && (
          <PDFErrorBoundary rawUrl={rawUrl}>
            <Suspense fallback={<div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)', fontSize: 13 }}>Loading PDF viewer…</div>}>
              <PDFViewer
                url={rawUrl}
                initialPage={pdfTarget && pdfTarget.path === currentFile ? pdfTarget.page : undefined}
              />
            </Suspense>
          </PDFErrorBoundary>
        )}

        {isDoc && (
          <div style={{ flex: 1, overflow: 'auto', padding: '32px 40px' }}>
            {textLoading
              ? <div style={{ color: 'var(--text-muted)', fontSize: 13 }}>Extracting text…</div>
              : <div className="prose" style={{ maxWidth: 680, whiteSpace: 'pre-wrap', fontSize: 14, lineHeight: 1.7 }}>
                  {textData?.text ?? `[${ext} — cannot extract text]`}
                </div>
            }
          </div>
        )}

        {(isImage || isAudio || isVideo) && (
          <div style={{ flex: 1, overflow: 'auto', display: 'flex', flexDirection: 'column', alignItems: 'flex-start', padding: 24, gap: 12 }}>
            {isImage && <img src={rawUrl} alt={currentFile!} style={{ maxWidth: '100%', objectFit: 'contain', borderRadius: 4 }} />}
            {isAudio && <audio controls src={rawUrl} style={{ width: '100%', maxWidth: 480 }} />}
            {isVideo && <video controls src={rawUrl} style={{ maxWidth: '100%', maxHeight: '80vh', borderRadius: 4 }} />}
          </div>
        )}

        {!isPDF && !isDoc && !isImage && !isAudio && !isVideo && (
          <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', flexDirection: 'column', gap: 12, color: 'var(--text-muted)' }}>
            <span style={{ fontSize: 36 }}>⊞</span>
            <span style={{ fontSize: 13 }}>{ext} — no preview available</span>
            <span style={{ fontSize: 11, fontFamily: 'var(--font-mono)' }}>{currentFile}</span>
          </div>
        )}
      </div>
    )
  }

  return (
    <div
      style={{
        flex: 1,
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
      }}
      data-testid="editor"
    >
      {/* Toolbar */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          padding: '8px 16px',
          borderBottom: '1px solid var(--border)',
          background: 'var(--bg-panel)',
          flexShrink: 0,
        }}
      >
        <button
          onClick={goBack}
          disabled={historyIndex <= 0}
          title="Back (⌘[)"
          style={{
            padding: '2px 7px',
            background: 'transparent',
            color: historyIndex <= 0 ? 'var(--text-muted)' : 'var(--text-secondary)',
            border: '1px solid var(--border)',
            borderRadius: 3,
            cursor: historyIndex <= 0 ? 'default' : 'pointer',
            fontSize: 12,
            opacity: historyIndex <= 0 ? 0.4 : 1,
          }}
        >
          ←
        </button>
        <button
          onClick={goForward}
          disabled={historyIndex >= history.length - 1}
          title="Forward (⌘])"
          style={{
            padding: '2px 7px',
            background: 'transparent',
            color: historyIndex >= history.length - 1 ? 'var(--text-muted)' : 'var(--text-secondary)',
            border: '1px solid var(--border)',
            borderRadius: 3,
            cursor: historyIndex >= history.length - 1 ? 'default' : 'pointer',
            fontSize: 12,
            opacity: historyIndex >= history.length - 1 ? 0.4 : 1,
          }}
        >
          →
        </button>
        <span style={{ flex: 1, color: 'var(--text-muted)', fontSize: 12, fontFamily: 'var(--font-mono)' }}>
          {currentFile}
        </span>
        {dirty && saveStatus === 'idle' && (
          <span style={{ color: 'var(--accent)', fontSize: 11 }}>● unsaved</span>
        )}
        {saveStatus === 'saving' && (
          <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>saving…</span>
        )}
        {saveStatus === 'saved' && (
          <span style={{ fontSize: 11, color: 'var(--success, #4caf50)' }}>✓ saved</span>
        )}
        {saveStatus === 'error' && (
          <span
            title={saveError ?? undefined}
            style={{ fontSize: 11, color: 'var(--error, #c05050)', display: 'flex', alignItems: 'center', gap: 4 }}
          >
            ⚠ save failed
            <button
              onClick={flush}
              style={{
                background: 'transparent',
                border: '1px solid var(--error, #c05050)',
                color: 'var(--error, #c05050)',
                borderRadius: 3,
                padding: '0 6px',
                fontSize: 10,
                cursor: 'pointer',
              }}
            >
              retry
            </button>
          </span>
        )}
        {speechSynthesisSupported && (
          <>
            {voices.length > 0 && (
              <select
                value={selectedVoiceURI}
                onChange={(e) => setSelectedVoiceURI(e.target.value)}
                title="Voice"
                style={{
                  padding: '2px 4px',
                  background: 'var(--bg-panel)',
                  color: 'var(--text-muted)',
                  border: '1px solid var(--border)',
                  borderRadius: 4,
                  cursor: 'pointer',
                  fontSize: 11,
                  maxWidth: 140,
                }}
              >
                <option value="">Default voice</option>
                {voices.map((v) => (
                  <option key={v.voiceURI} value={v.voiceURI}>
                    {v.name} ({v.lang})
                  </option>
                ))}
              </select>
            )}
            <button
              onClick={toggleRead}
              title={speaking ? 'Stop reading' : 'Read aloud'}
              style={{
                padding: '3px 8px',
                background: speaking ? 'var(--accent-dim)' : 'transparent',
                color: speaking ? 'var(--accent)' : 'var(--text-muted)',
                border: '1px solid var(--border)',
                borderRadius: 4,
                cursor: 'pointer',
                fontSize: 12,
              }}
            >
              {speaking ? '⏹ Stop' : '▶ Read'}
            </button>
          </>
        )}
        <button
          onClick={() => setEditMode((m) => !m)}
          style={{
            padding: '3px 10px',
            background: editMode ? 'var(--accent-dim)' : 'transparent',
            color: editMode ? 'var(--accent)' : 'var(--text-secondary)',
            border: '1px solid var(--border)',
            borderRadius: 4,
            cursor: 'pointer',
            fontSize: 12,
          }}
        >
          {editMode ? 'View' : 'Edit'}
        </button>
        {editMode && (
          <button
            onClick={flush}
            disabled={!dirty || saveMutation.isPending}
            title={dirty ? 'Save now (⌘S)' : 'Nothing to save'}
            style={{
              padding: '3px 10px',
              background: dirty ? 'var(--accent)' : 'transparent',
              color: dirty ? 'var(--on-accent)' : 'var(--text-muted)',
              border: '1px solid ' + (dirty ? 'var(--accent)' : 'var(--border)'),
              borderRadius: 4,
              cursor: dirty && !saveMutation.isPending ? 'pointer' : 'not-allowed',
              fontSize: 12,
              opacity: saveMutation.isPending ? 0.6 : 1,
              fontWeight: dirty ? 600 : 400,
            }}
          >
            {saveMutation.isPending ? 'Saving…' : 'Save'}
          </button>
        )}
      </div>

      {/* Content */}
      <div
        style={{
          flex: 1,
          overflow: 'auto',
          padding: panelMode === 'focus' ? '40px calc(50% - 340px)' : '32px 40px',
          display: 'flex',
          justifyContent: panelMode === 'focus' ? 'center' : 'flex-start',
        }}
      >
        {editMode ? (
          <div
            style={{ width: '100%', maxWidth: panelMode === 'focus' ? 680 : '100%' }}
          >
            <CodeMirror
              ref={cmRef}
              value={draft}
              extensions={cmExtensions}
              theme={cmTheme}
              onChange={(val) => {
                // Sync refs BEFORE scheduling the timer. The state-driven
                // sync effects run after commit, which can lag a fast typer
                // by a frame or two — updating refs synchronously here means
                // a 700ms timer fired right after the last keystroke always
                // sees the latest content.
                draftRef.current = val
                dirtyRef.current = true
                setDraft(val)
                setDirty(true)
                setSaveStatus('idle')
                setSaveError(null)
                if (saveTimerRef.current) clearTimeout(saveTimerRef.current)
                saveTimerRef.current = setTimeout(() => { flush() }, 700)
              }}
              style={{ fontSize: 14 }}
            />
          </div>
        ) : data?.ext === '.html' || data?.ext === '.htm' ? (
          // HTML View mode: render the buffer in a FULLY sandboxed iframe.
          //
          // `sandbox=""` — an empty value, not a missing one — is the whole
          // security story, and it is not optional here. The desktop shell runs
          // with `withGlobalTauri: true` and `csp: null`, so anything executing
          // in this page's origin can reach `window.__TAURI__` and, through it,
          // the dialog plugin. Vault HTML is arbitrary: saved web pages, export
          // output, files synced in from Drive or Dropbox. `dangerouslySetInner
          // HTML` would run every inline script in that content with the app's
          // own privileges, which is a far worse trade than "some pages render
          // without their JavaScript".
          //
          // The empty value withholds every token at once: no `allow-scripts`
          // (inline and external JS never runs), no `allow-same-origin` (the
          // frame gets an opaque origin, so it cannot touch this document, its
          // storage, or its globals — and note that granting BOTH of those
          // together would let the frame remove its own sandbox attribute),
          // no `allow-top-navigation` (a page cannot navigate the app away from
          // itself), no `allow-forms`, no `allow-popups`. Static HTML and CSS
          // still render, which is what "render the HTML" means for notes.
          //
          // Switch to Edit to see the source. Do not "fix" a page that needs
          // scripts by widening this — open it in a real browser instead.
          <div
            style={{
              width: '100%',
              // Same reasoning as the SVG sheet below: HTML is authored against
              // a white page, and on the app's near-black surface a document
              // with no background of its own renders dark-on-dark.
              background: PREVIEW_PAPER,
              borderRadius: 4,
              overflow: 'hidden',
            }}
          >
            <iframe
              title={currentFile ?? 'HTML preview'}
              srcDoc={draft || data?.content || ''}
              sandbox=""
              referrerPolicy="no-referrer"
              style={{
                display: 'block',
                width: '100%',
                height: 'min(80vh, 900px)',
                border: 'none',
                background: PREVIEW_PAPER,
              }}
            />
          </div>
        ) : data?.ext === '.svg' ? (
          // SVG View mode: render the current buffer as an image (data-URL —
          // <img> never executes embedded scripts, so this is safe even for
          // un-sanitized source). Switch to Edit to fix the XML source.
          //
          // The white canvas is load-bearing: generated SVGs use dark strokes
          // on a transparent background, so on the app's near-black surface
          // (--bg-base) the lines are invisible. White matches Chrome's default
          // page and makes them visible.
          <div
            style={{
              width: '100%',
              display: 'flex',
              justifyContent: 'center',
              alignItems: 'flex-start',
              // Not a token: this is the paper sheet the rendered markdown
              // sits on. It must stay white in BOTH themes — a theme-reactive
              // token would turn the page dark and the text with it.
              background: '#fff',
              padding: 16,
              borderRadius: 4,
            }}
          >
            <img
              src={`data:image/svg+xml;utf8,${encodeURIComponent(draft || data?.content || '')}`}
              alt={currentFile ?? 'SVG preview'}
              style={{ maxWidth: '100%', objectFit: 'contain' }}
            />
          </div>
        ) : (
          // Event-delegation root for rendered markdown: the click handler
          // inspects the target to intercept wikilink clicks. The anchors inside
          // are real links and are keyboard-activatable on their own.
          // eslint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/no-static-element-interactions
          <div
            className="prose"
            style={{ width: '100%', maxWidth: 680 }}
            onClick={(e) => {
              const target = e.target as HTMLElement
              const MOUNTS = ['notes/', 'library/', 'generated/']
              const hasMountPrefix = (p: string) => MOUNTS.some((m) => p.startsWith(m))

              // Internal wikilinks / vault paths
              const a = target.closest('a[data-library-path]')
              if (a) {
                e.preventDefault()
                const path = a.getAttribute('data-library-path')!
                if (hasMountPrefix(path)) {
                  // Full mount-prefixed path — navigate directly
                  setCurrentFile(path)
                } else {
                  // Bare wikilink name — search for the file
                  const name = path.split('/').pop() ?? path
                  api.findFile(name).then(({ results }) => {
                    if (results.length > 0) setCurrentFile(results[0])
                  }).catch((e) => console.error('wikilink file lookup failed', e))
                }
                return
              }
              // Code spans that look like file references
              const code = target.closest('code[data-file-search]')
              if (code) {
                e.preventDefault()
                const query = code.getAttribute('data-file-search')!
                if (hasMountPrefix(query)) {
                  // Full path — navigate directly without an ambiguous name search
                  setCurrentFile(query)
                } else {
                  const name = query.split('/').pop() ?? query
                  api.findFile(name).then(({ results }) => {
                    if (results.length > 0) setCurrentFile(results[0])
                  }).catch((e) => console.error('wikilink file lookup failed', e))
                }
              }
            }}
          >
            <div dangerouslySetInnerHTML={{ __html: renderMarkdown(viewBody, { notePath: currentFile }) }} />
          </div>
        )}
      </div>
    </div>
  )
}
