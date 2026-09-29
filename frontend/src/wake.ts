import { useEffect, useState } from 'react'
import { ERRORS, LANG, recognitionCtor, type Recognition } from './voice'

// "Jarvis" as the Thai recognizer tends to write it: จาร์วิส, จาวิส, จาร์วิด, Jarvis…
const NAME = '(?:jarvis|จา(?:ร์|ร)?วิ(?:ส|ซ|ด|ท|ต))'
// Only "Hey Jarvis" / "เฮ้ จาร์วิส" wakes it, so just mentioning the name in conversation doesn't.
const WAKE_WORD = new RegExp(`(?:hey|เฮ้|เฮ|เฮย์|เฮย)\\s*${NAME}`, 'i')
const MENTIONS_NAME = new RegExp(NAME, 'i')
const NAME_ONLY = new RegExp(`^\\s*${NAME}\\s*[.!?]?\\s*$`, 'i')
// "Jarvis หยุดการทำงาน", "stop Jarvis": turns hands-free mode off.
const STOP_WORDS = /(?:หยุดการทำงาน|หยุดทำงาน|หยุดฟัง|ปิดโหมดปลุก|\bstop\b|สต็อป|สต๊อป|สตอป)/i
// How long to wait for the command after the wake word (or after JARVIS answers).
export const COMMAND_WINDOW_MS = 8000
// Chrome's continuous mode is slow to mark speech final; once the words stop changing for this long, act on them.
const SETTLE_MS = 700
const FATAL_ERRORS = new Set(['not-allowed', 'service-not-allowed', 'audio-capture'])

export type WakeMode = 'waiting' | 'command'

/** The command in a sentence that contains the wake word ("เฮ้ จาร์วิส เปิดไฟ" → "เปิดไฟ"), or null without it. */
export function findWakeWord(text: string): { command: string } | null {
  const m = WAKE_WORD.exec(text)
  if (!m) return null
  return { command: text.slice(m.index + m[0].length).replace(/^[\s,.!?]+/, '').trim() }
}

/** True for a stop phrase addressed to JARVIS (or said while it's already listening for a command). */
export function isStopCommand(text: string, awake: boolean): boolean {
  return STOP_WORDS.test(text) && (awake || MENTIONS_NAME.test(text))
}

interface Callbacks {
  onStop: () => void
  onMode: (mode: WakeMode) => void
  onHeard: (text: string) => void
  onWake: () => void
  onFatal: (message: string) => void
}

/**
 * Continuous listening for the wake word. The browser ends recognition sessions on its own
 * (silence, time limits, network), so it restarts until paused.
 */
class WakeListener {
  private rec: Recognition | null = null
  private mode: WakeMode = 'waiting'
  private timer: number | undefined
  private settle: number | undefined
  private running = false
  private restartDelay = 100
  private cb: Callbacks
  private onCommand: (text: string) => void = () => {}

  constructor(cb: Callbacks) {
    this.cb = cb
  }

  /** Updated by the component on every render so commands go to the current conversation. */
  setOnCommand(fn: (text: string) => void) {
    this.onCommand = fn
  }

  resume() {
    this.running = true
    this.listen()
  }

  pause() {
    window.clearTimeout(this.settle)
    this.running = false
    this.rec?.abort()
    this.rec = null
    this.cb.onHeard('')
  }

  /** Take the next sentence as a command without the wake word (mic button, or a follow-up after a reply). */
  expectCommand() {
    this.setMode('command')
  }

  private setMode(mode: WakeMode) {
    window.clearTimeout(this.timer)
    this.mode = mode
    this.cb.onMode(mode)
    if (mode === 'command') this.timer = window.setTimeout(() => this.setMode('waiting'), COMMAND_WINDOW_MS)
  }

  private listen() {
    const Ctor = recognitionCtor()
    if (!Ctor || this.rec || !this.running) return
    const r = new Ctor()
    r.lang = LANG
    r.continuous = true
    r.interimResults = true
    r.onresult = (e) => {
      window.clearTimeout(this.settle)
      let interim = ''
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const res = e.results[i]
        if (res.isFinal) this.handle(res[0].transcript)
        else interim += res[0].transcript
      }
      this.cb.onHeard(interim)
      if (interim && this.isForUs(interim)) {
        this.settle = window.setTimeout(() => this.settleEarly(r, interim), SETTLE_MS)
      }
    }
    r.onerror = (e) => {
      if (FATAL_ERRORS.has(e.error)) {
        this.running = false
        this.cb.onFatal(ERRORS[e.error])
      } else if (e.error === 'network') {
        this.restartDelay = Math.min(this.restartDelay * 2, 10_000)
      }
      // 'no-speech' and 'aborted' are routine: onend restarts (or not, when paused).
    }
    r.onend = () => {
      if (this.rec === r) this.rec = null
      this.cb.onHeard('')
      if (this.running) window.setTimeout(() => this.listen(), this.restartDelay)
    }
    this.rec = r
    try {
      r.start()
    } catch {
      this.rec = null
    }
  }

  /** Speech worth acting on before Chrome finalizes it: a command, the wake word, or a stop phrase. */
  private isForUs(text: string) {
    return this.mode === 'command' || findWakeWord(text) !== null || isStopCommand(text, false)
  }

  /** Act on the interim words now and drop this session so the late final result isn't handled twice. */
  private settleEarly(r: Recognition, text: string) {
    if (this.rec !== r) return
    this.rec = null
    r.abort() // onend restarts listening while running
    this.cb.onHeard('')
    this.handle(text)
  }

  private handle(transcript: string) {
    this.restartDelay = 100
    const text = transcript.trim()
    if (!text) return
    if (isStopCommand(text, this.mode === 'command')) {
      // Cancel whatever it was listening for and go back to waiting for "Hey Jarvis"; the mic stays on.
      this.setMode('waiting')
      this.cb.onStop()
      return
    }
    if (this.mode === 'command') {
      const again = findWakeWord(text)
      if ((again && again.command.length < 2) || NAME_ONLY.test(text)) {
        // Just the wake word again: keep listening for the command.
        this.cb.onWake()
        this.setMode('command')
        return
      }
      this.setMode('waiting')
      // Saying the wake word again while it's already listening shouldn't end up in the command.
      this.onCommand(findWakeWord(text)?.command || text)
      return
    }
    const wake = findWakeWord(text)
    if (!wake) return
    this.cb.onWake()
    if (wake.command.length >= 2) this.onCommand(wake.command)
    else this.setMode('command')
  }
}

let audioCtx: AudioContext | null = null

/** A short rising "ding" when JARVIS starts listening for a command; falling when it stops. */
export function chime(direction: 'up' | 'down' = 'up') {
  try {
    audioCtx ??= new AudioContext()
    void audioCtx.resume()
    const t = audioCtx.currentTime
    const osc = audioCtx.createOscillator()
    const gain = audioCtx.createGain()
    const [first, second] = direction === 'up' ? [880, 1320] : [1320, 660]
    osc.frequency.setValueAtTime(first, t)
    osc.frequency.setValueAtTime(second, t + 0.09)
    gain.gain.setValueAtTime(0.0001, t)
    gain.gain.exponentialRampToValueAtTime(0.2, t + 0.01)
    gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.28)
    osc.connect(gain).connect(audioCtx.destination)
    osc.start(t)
    osc.stop(t + 0.3)
  } catch {
    // no audio output available; the status text still shows it's listening
  }
}

const STORAGE_KEY = 'jarvis.wake'

function loadEnabled(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === 'on'
  } catch {
    return false
  }
}

function saveEnabled(on: boolean) {
  try {
    localStorage.setItem(STORAGE_KEY, on ? 'on' : 'off')
  } catch {
    // not remembered across reloads; fine
  }
}

/** Always-on "Hey Jarvis" listening, paused while JARVIS is thinking or talking. */
export function useWakeWord(onCommand: (text: string) => void, paused: boolean) {
  const [enabled, setEnabledState] = useState(loadEnabled)
  const [mode, setMode] = useState<WakeMode>('waiting')
  const [heard, setHeard] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [listener] = useState(
    () =>
      new WakeListener({
        onMode: setMode,
        onHeard: setHeard,
        onWake: () => chime(),
        onStop: () => chime('down'),
        onFatal: (message) => {
          setError(message)
          setEnabledState(false)
        },
      }),
  )

  useEffect(() => {
    listener.setOnCommand(onCommand)
  }, [listener, onCommand])

  useEffect(() => {
    if (enabled && !paused) listener.resume()
    else listener.pause()
  }, [enabled, paused, listener])

  useEffect(() => () => listener.pause(), [listener])

  function setEnabled(on: boolean) {
    saveEnabled(on)
    setError(null)
    setEnabledState(on)
  }

  // What's being said to JARVIS right now (not background talk), for a live bubble in the chat.
  const speakingToJarvis = heard && (mode === 'command' || findWakeWord(heard) !== null) ? heard : ''

  return {
    enabled,
    speakingToJarvis,
    setEnabled,
    mode,
    heard,
    error,
    /** Listen for a command right away (mic button, or a follow-up after JARVIS answers). */
    expectCommand: () => listener.expectCommand(),
  }
}
