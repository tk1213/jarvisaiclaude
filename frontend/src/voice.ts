import { useCallback, useEffect, useRef, useState } from 'react'
import { api, getToken } from './api'

// Browser speech APIs: recognition (STT) is prefixed in Chrome/Edge and missing from lib.dom.
interface RecognitionResult {
  isFinal: boolean
  0: { transcript: string }
}
interface RecognitionEvent {
  resultIndex: number
  results: ArrayLike<RecognitionResult>
}
export interface Recognition {
  lang: string
  interimResults: boolean
  continuous: boolean
  onresult: ((e: RecognitionEvent) => void) | null
  onerror: ((e: { error: string }) => void) | null
  onend: (() => void) | null
  start(): void
  stop(): void
  abort(): void
}
export type RecognitionCtor = new () => Recognition

export const LANG = 'th-TH'

export function recognitionCtor(): RecognitionCtor | null {
  const w = window as unknown as { SpeechRecognition?: RecognitionCtor; webkitSpeechRecognition?: RecognitionCtor }
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null
}

export const sttSupported = typeof window !== 'undefined' && recognitionCtor() !== null
export const ttsSupported = typeof window !== 'undefined' && 'speechSynthesis' in window

export const ERRORS: Record<string, string> = {
  'not-allowed': 'เบราว์เซอร์ไม่ได้รับอนุญาตให้ใช้ไมค์ กดไอคอนแม่กุญแจที่แถบที่อยู่แล้วอนุญาตไมโครโฟน',
  'service-not-allowed': 'เบราว์เซอร์ไม่อนุญาตให้ใช้ระบบแปลงเสียง',
  'audio-capture': 'ไม่พบไมโครโฟน ตรวจว่าเสียบไมค์แล้ว',
  network: 'ต่อบริการแปลงเสียงไม่ได้ (ต้องต่ออินเทอร์เน็ต)',
  'no-speech': 'ไม่ได้ยินเสียง ลองกดไมค์แล้วพูดใหม่',
}

/** One-shot speech recognition in Thai: start(), speak, and onFinal receives the sentence. */
export function useSpeechRecognition(onFinal: (text: string) => void) {
  const [listening, setListening] = useState(false)
  const [interim, setInterim] = useState('')
  const [error, setError] = useState<string | null>(null)
  const recognition = useRef<Recognition | null>(null)
  const latestOnFinal = useRef(onFinal)

  useEffect(() => {
    latestOnFinal.current = onFinal
  }, [onFinal])

  useEffect(() => () => recognition.current?.abort(), [])

  const start = useCallback(() => {
    const Ctor = recognitionCtor()
    if (!Ctor || recognition.current) return
    const r = new Ctor()
    r.lang = LANG
    r.interimResults = true
    r.continuous = false
    let finalText = ''
    r.onresult = (e) => {
      let partial = ''
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const res = e.results[i]
        if (res.isFinal) finalText += res[0].transcript
        else partial += res[0].transcript
      }
      setInterim(finalText + partial)
    }
    r.onerror = (e) => {
      if (e.error !== 'aborted') setError(ERRORS[e.error] ?? `แปลงเสียงไม่สำเร็จ (${e.error})`)
    }
    r.onend = () => {
      recognition.current = null
      setListening(false)
      setInterim('')
      const text = finalText.trim()
      if (text) latestOnFinal.current(text)
    }
    recognition.current = r
    setError(null)
    setInterim('')
    setListening(true)
    r.start()
  }, [])

  /** Stop listening; whatever was heard so far is still delivered. */
  const stop = useCallback(() => recognition.current?.stop(), [])

  return { listening, interim, error, start, stop }
}

// Thai female voices, best first: Edge's natural Premwadee, Achara, then Google's.
const PREFERRED_VOICES = [/premwadee/i, /achara/i, /google/i]
// Windows' Pattara and Edge's Niwat are male.
const MALE_VOICES = /niwat|pattara/i
// A slightly higher, quicker delivery for a bright, youthful sound.
const PITCH = 1.15
const RATE = 1.05

function thaiVoice(): SpeechSynthesisVoice | null {
  const voices = speechSynthesis.getVoices().filter((v) => v.lang.toLowerCase().startsWith('th'))
  for (const name of PREFERRED_VOICES) {
    const match = voices.find((v) => name.test(v.name))
    if (match) return match
  }
  // Never fall back to a male voice: silence (with a notice) is better than the wrong voice.
  return voices.find((v) => !MALE_VOICES.test(v.name)) ?? null
}

/** True once voices are loaded and none speaks Thai (the browser then reads with a foreign accent or not at all). */
export function useMissingThaiVoice(): boolean {
  const [missing, setMissing] = useState(false)
  useEffect(() => {
    if (!ttsSupported) return
    const check = () => setMissing(speechSynthesis.getVoices().length > 0 && thaiVoice() === null)
    check()
    speechSynthesis.addEventListener('voiceschanged', check)
    return () => speechSynthesis.removeEventListener('voiceschanged', check)
  }, [])
  return missing
}

/** Strip markdown-ish symbols so they aren't read aloud, and split into short chunks (Chrome cuts off long utterances). */
// Words the voices would otherwise spell out letter by letter ("J-A-R-V-I-S").
const PRONUNCIATIONS: [RegExp, string][] = [
  [/(?<![a-z])j[.\s]*a[.\s]*r[.\s]*v[.\s]*i[.\s]*s(?![a-z])\.?/gi, 'จาร์วิส'], // JARVIS, J.A.R.V.I.S.
  [/เจ\s*เอ\s*อาร์\s*วี\s*ไอ\s*เอส/g, 'จาร์วิส'], // spelled out in Thai letters
]

function chunks(text: string): string[] {
  const clean = PRONUNCIATIONS.reduce((t, [pattern, spoken]) => t.replace(pattern, spoken), text)
    .replace(/[*_`#>|]/g, '')
    .replace(/^\s*[-•]\s+/gm, '')
    .replace(/\s+/g, ' ')
    .trim()
  const parts: string[] = []
  let current = ''
  for (const word of clean.split(' ')) {
    if (current && current.length + word.length > 180) {
      parts.push(current)
      current = word
    } else {
      current = current ? `${current} ${word}` : word
    }
  }
  if (current) parts.push(current)
  return parts
}

// --- Coordination between dashboard tabs, and echo protection ---------------------------------------
// Two open dashboards would hear each other's replies and answer them in a loop, so only one tab
// listens at a time, every tab pauses while any tab is talking, and JARVIS's own recent replies
// are never taken as commands.

export const TAB_ID = Math.random().toString(36).slice(2)
export type VoiceMessage = { type: 'speaking'; on: boolean; text?: string; tab: string } | { type: 'listening'; tab: string }
type Outgoing = { type: 'speaking'; on: boolean; text?: string } | { type: 'listening' }

const channel = typeof BroadcastChannel !== 'undefined' ? new BroadcastChannel('jarvis-voice') : null
const listeners = new Set<(m: VoiceMessage) => void>()
channel?.addEventListener('message', (e: MessageEvent<VoiceMessage>) => {
  if (e.data.type === 'speaking' && e.data.text) rememberSpoken(e.data.text)
  listeners.forEach((fn) => fn(e.data))
})

export function broadcast(message: Outgoing) {
  channel?.postMessage({ ...message, tab: TAB_ID })
}

/** Messages from other dashboard tabs; returns an unsubscribe function. */
export function subscribeVoice(fn: (m: VoiceMessage) => void) {
  listeners.add(fn)
  return () => {
    listeners.delete(fn)
  }
}

const ECHO_WINDOW_MS = 60_000
const recentlySpoken: { text: string; at: number }[] = []

function normalize(text: string) {
  return text.toLowerCase().replace(/[\s.,!?'"“”…:;()-]/g, '')
}

function rememberSpoken(text: string) {
  recentlySpoken.push({ text: normalize(text), at: Date.now() })
  if (recentlySpoken.length > 10) recentlySpoken.shift()
}

/** True if what the mic heard is (mostly) something JARVIS said in the last minute. */
export function isEcho(heard: string): boolean {
  const h = normalize(heard)
  if (h.length < 6) return false
  const pairs = Array.from({ length: h.length - 1 }, (_, i) => h.slice(i, i + 2))
  return recentlySpoken.some(({ text, at }) => {
    // A short answer like "ยืนยัน" can appear inside a reply; only a sizeable chunk of the reply counts.
    if (Date.now() - at > ECHO_WINDOW_MS || h.length < text.length * 0.4) return false
    const found = pairs.filter((p) => text.includes(p)).length
    return found / pairs.length >= 0.6
  })
}

// Browsers load voices lazily; asking early means they're ready by the first reply
// (otherwise the first reply falls back to the system's default, often male, voice).
if (ttsSupported) speechSynthesis.getVoices()

// Server first: if its voice isn't available the reply falls back to the browser's voice.
let engine: 'server' | 'browser' = 'server'
// Spoken replies are short; this also keeps the streaming URL well under server limits.
const MAX_SPOKEN_CHARS = 600
let audio: HTMLAudioElement | null = null
// Bumped on every speak/stop so a slow server response can't start talking after it was cancelled.
let generation = 0

/** "server" when the backend synthesizes speech (Edge neural voice), from /voice/config. */
export function setVoiceEngine(value: 'server' | 'browser') {
  engine = value
}

export function usesServerVoice() {
  return engine === 'server'
}

/**
 * Read text aloud in Thai; onEnd fires when finished or cancelled. onFallback is told why
 * the server voice wasn't used when the browser's own voice had to stand in.
 */
export function speak(text: string, whenDone?: () => void, onFallback?: (reason: string) => void) {
  stopSpeaking()
  const id = generation
  // Other tabs pause their mic while this one talks, and every tab ignores this text if the mic picks it up.
  rememberSpoken(text)
  broadcast({ type: 'speaking', on: true, text })
  const onEnd = () => {
    broadcast({ type: 'speaking', on: false })
    whenDone?.()
  }
  if (engine !== 'server') return speakWithBrowser(text, onEnd)
  const clean = chunks(text).join(' ').slice(0, MAX_SPOKEN_CHARS)
  if (!clean) return onEnd?.()

  const useBrowser = (reason: string) => {
    if (id !== generation) return onEnd?.()
    onFallback?.(reason)
    speakWithBrowser(text, onEnd)
  }
  // Streamed: playback starts while the server is still synthesizing the rest of the reply.
  const url = `/voice/tts?text=${encodeURIComponent(clean)}&token=${encodeURIComponent(getToken() ?? '')}`
  play(url, id, onEnd, () => {
    // The stream failed before any sound; ask why (the server already retried, so don't synthesize again).
    api
      .voiceLastError()
      .then((r) => useBrowser(r.error ?? 'เล่นเสียงไม่ได้'))
      .catch(() => useBrowser('เล่นเสียงไม่ได้'))
  })
}

/** Play src; onFail runs instead of onEnd if it errors before making any sound. */
function play(src: string, id: number, onEnd: (() => void) | undefined, onFail: () => void, cleanup?: () => void) {
  const player = new Audio(src)
  audio = player
  let started = false
  let finished = false
  const finish = (failed: boolean) => {
    // 'pause' also fires when playback ends, so guard against running twice.
    if (finished) return
    finished = true
    cleanup?.()
    if (audio === player) audio = null
    if (failed && !started && id === generation) onFail()
    else onEnd?.()
  }
  player.onplaying = () => {
    started = true
  }
  player.onended = () => finish(false)
  player.onpause = () => finish(false)
  player.onerror = () => finish(true)
  player.play().catch(() => finish(true))
}

function speakWithBrowser(text: string, onEnd?: () => void) {
  if (!ttsSupported) return onEnd?.()
  const parts = chunks(text)
  const voice = thaiVoice()
  if (parts.length === 0 || !voice) return onEnd?.()
  parts.forEach((part, i) => {
    const u = new SpeechSynthesisUtterance(part)
    u.lang = LANG
    u.pitch = PITCH
    u.rate = RATE
    u.voice = voice
    if (i === parts.length - 1) {
      u.onend = () => onEnd?.()
      u.onerror = () => onEnd?.()
    }
    speechSynthesis.speak(u)
  })
}

export function stopSpeaking() {
  generation++
  audio?.pause()
  audio = null
  if (ttsSupported) speechSynthesis.cancel()
}
