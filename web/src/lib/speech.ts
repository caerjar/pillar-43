/**
 * Web Speech API utilities.
 *
 * SpeechRecognition: speech → text (mic input)
 * SpeechSynthesis:   text → speech (read aloud)
 *
 * Both APIs are available in Chrome, Edge, and Safari. Firefox does not
 * support SpeechRecognition natively as of 2025.
 */

// ── Speech Recognition (mic → text) ─────────────────────────────────────────

const SR = (window as any).SpeechRecognition ?? (window as any).webkitSpeechRecognition

export const speechRecognitionSupported = !!SR

export type RecognitionState = 'idle' | 'listening' | 'stopping'

export interface RecognitionCallbacks {
  onInterim: (text: string) => void    // live partial result
  onFinal: (text: string) => void      // committed result
  onEnd: () => void
  onError: (msg: string) => void
}

export interface RecognitionOpts {
  /** BCP-47 language tag, e.g. "en-US", "fr", "es-MX". Defaults to "en-US". */
  lang?: string
}

/**
 * Create a SpeechRecognition instance configured for a single short utterance
 * (voice-to-scratch-pad use case). The instance should be discarded after use.
 */
export function createOneShot(
  callbacks: RecognitionCallbacks,
  opts?: RecognitionOpts,
): SpeechRecognition | null {
  if (!SR) return null
  const rec: SpeechRecognition = new SR()
  rec.lang = opts?.lang || 'en-US'
  rec.interimResults = true
  rec.continuous = false
  rec.maxAlternatives = 1

  rec.onresult = (e: SpeechRecognitionEvent) => {
    let interim = ''
    let final = ''
    for (let i = e.resultIndex; i < e.results.length; i++) {
      const t = e.results[i][0].transcript
      if (e.results[i].isFinal) final += t
      else interim += t
    }
    if (interim) callbacks.onInterim(interim)
    if (final) callbacks.onFinal(final)
  }

  rec.onend = () => callbacks.onEnd()
  rec.onerror = (e: SpeechRecognitionErrorEvent) => callbacks.onError(e.error)

  return rec
}

/**
 * Create a SpeechRecognition instance for continuous dictation (transcription
 * mode). Stays open until stop() is called.
 */
export function createContinuous(
  callbacks: RecognitionCallbacks,
  opts?: RecognitionOpts,
): SpeechRecognition | null {
  if (!SR) return null
  const rec: SpeechRecognition = new SR()
  rec.lang = opts?.lang || 'en-US'
  rec.interimResults = true
  rec.continuous = true
  rec.maxAlternatives = 1

  rec.onresult = (e: SpeechRecognitionEvent) => {
    let interim = ''
    let final = ''
    for (let i = e.resultIndex; i < e.results.length; i++) {
      const t = e.results[i][0].transcript
      if (e.results[i].isFinal) final += t
      else interim += t
    }
    if (interim) callbacks.onInterim(interim)
    if (final) callbacks.onFinal(final)
  }

  rec.onend = () => callbacks.onEnd()
  rec.onerror = (e: SpeechRecognitionErrorEvent) => callbacks.onError(e.error)

  return rec
}

// ── Speech Synthesis (text → voice) ─────────────────────────────────────────

export const speechSynthesisSupported = 'speechSynthesis' in window

export interface SpeechOpts {
  /** BCP-47 language tag for the utterance, e.g. "fr", "es". */
  lang?: string
  /** A specific SpeechSynthesisVoice to use. */
  voice?: SpeechSynthesisVoice | null
}

/**
 * Read text aloud using the browser's speech synthesis.
 * Returns a cancel function.
 */
export function speak(
  text: string,
  onEnd?: () => void,
  opts?: SpeechOpts,
): () => void {
  if (!speechSynthesisSupported) return () => {}
  window.speechSynthesis.cancel()

  // Split into chunks at sentence boundaries so the browser doesn't cut off
  // long texts (some engines have a ~32 KB utterance limit).
  const chunks = splitIntoChunks(text, 3000)
  let idx = 0

  function speakNext() {
    if (idx >= chunks.length) {
      onEnd?.()
      return
    }
    const utt = new SpeechSynthesisUtterance(chunks[idx++])
    utt.rate = 0.95
    if (opts?.lang) utt.lang = opts.lang
    if (opts?.voice) utt.voice = opts.voice
    utt.onend = speakNext
    utt.onerror = () => onEnd?.()
    window.speechSynthesis.speak(utt)
  }

  speakNext()

  return () => {
    window.speechSynthesis.cancel()
    onEnd?.()
  }
}

export function stopSpeaking() {
  if (speechSynthesisSupported) window.speechSynthesis.cancel()
}

/**
 * Load all available synthesis voices. In Chrome/Edge the list is populated
 * asynchronously after `voiceschanged` fires. Pass a callback to be notified
 * when voices are ready.
 */
export function loadVoices(onReady: (voices: SpeechSynthesisVoice[]) => void): () => void {
  if (!speechSynthesisSupported) return () => {}

  const voices = window.speechSynthesis.getVoices()
  if (voices.length > 0) {
    onReady(voices)
    return () => {}
  }

  const handler = () => onReady(window.speechSynthesis.getVoices())
  window.speechSynthesis.addEventListener('voiceschanged', handler)
  return () => window.speechSynthesis.removeEventListener('voiceschanged', handler)
}

function splitIntoChunks(text: string, maxLen: number): string[] {
  const sentences = text.match(/[^.!?\n]+[.!?\n]*/g) ?? [text]
  const chunks: string[] = []
  let buf = ''
  for (const s of sentences) {
    if (buf.length + s.length > maxLen) {
      if (buf) chunks.push(buf.trim())
      buf = s
    } else {
      buf += s
    }
  }
  if (buf.trim()) chunks.push(buf.trim())
  return chunks.length ? chunks : [text]
}
