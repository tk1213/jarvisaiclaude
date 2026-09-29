import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api'

// Browser speech APIs: recognition (STT) is prefixed in Chrome/Edge and missing from lib.dom.
interface RecognitionResult {
  isFinal: boolean
  0: { transcript: string }
}
interface RecognitionEvent {
  resultIndex: number
  results: ArrayLike<RecognitionResult>
}
interface Recognition {
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
type RecognitionCtor = new () => Recognition

const LANG = 'th-TH'

function recognitionCtor(): RecognitionCtor | null {
  const w = window as unknown as { SpeechRecognition?: RecognitionCtor; webkitSpeechRecognition?: RecognitionCtor }
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null
}

export const sttSupported = typeof window !== 'undefined' && recognitionCtor() !== null
export const ttsSupported = typeof window !== 'undefined' && 'speechSynthesis' in window

const ERRORS: Record<string, string> = {
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

// Thai female voices, best first: Edge's natural Premwadee, other Microsoft voices, then Google's.
const PREFERRED_VOICES = [/premwadee/i, /achara/i, /pattara/i, /google/i]
const MALE_VOICES = /niwat/i
// A slightly higher, quicker delivery for a bright, youthful sound.
const PITCH = 1.15
const RATE = 1.05

function thaiVoice(): SpeechSynthesisVoice | null {
  const voices = speechSynthesis.getVoices().filter((v) => v.lang.toLowerCase().startsWith('th'))
  for (const name of PREFERRED_VOICES) {
    const match = voices.find((v) => name.test(v.name))
    if (match) return match
  }
  return voices.find((v) => !MALE_VOICES.test(v.name)) ?? voices[0] ?? null
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
function chunks(text: string): string[] {
  const clean = text
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

// Browsers load voices lazily; asking early means they're ready by the first reply
// (otherwise the first reply falls back to the system's default, often male, voice).
if (ttsSupported) speechSynthesis.getVoices()

let engine: 'google' | 'browser' = 'browser'
let audio: HTMLAudioElement | null = null
// Bumped on every speak/stop so a slow Google response can't start talking after it was cancelled.
let generation = 0

/** "google" when the server has a Google Text-to-Speech key (set from /voice/config). */
export function setVoiceEngine(value: 'google' | 'browser') {
  engine = value
}

export function usesGoogleVoice() {
  return engine === 'google'
}

/** Read text aloud in Thai; onEnd fires when finished or cancelled. */
export function speak(text: string, onEnd?: () => void) {
  stopSpeaking()
  const id = generation
  if (engine === 'google') {
    const clean = chunks(text).join(' ')
    if (!clean) return onEnd?.()
    api
      .tts(clean)
      .then((blob) => {
        if (id !== generation) return onEnd?.()
        const url = URL.createObjectURL(blob)
        const player = new Audio(url)
        audio = player
        let finished = false
        // 'pause' also fires when playback ends, so guard against running twice.
        const done = () => {
          if (finished) return
          finished = true
          URL.revokeObjectURL(url)
          if (audio === player) audio = null
          onEnd?.()
        }
        player.onended = done
        player.onerror = done
        player.onpause = done
        return player.play()
      })
      .catch(() => {
        // Google unreachable or key rejected: still answer, with the browser's voice.
        if (id === generation) speakWithBrowser(text, onEnd)
        else onEnd?.()
      })
    return
  }
  speakWithBrowser(text, onEnd)
}

function speakWithBrowser(text: string, onEnd?: () => void) {
  if (!ttsSupported) return onEnd?.()
  const parts = chunks(text)
  if (parts.length === 0) return onEnd?.()
  const voice = thaiVoice()
  parts.forEach((part, i) => {
    const u = new SpeechSynthesisUtterance(part)
    u.lang = LANG
    u.pitch = PITCH
    u.rate = RATE
    if (voice) u.voice = voice
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
