import { useEffect, useState } from 'react'
import { broadcast, ERRORS, isEcho, LANG, recognitionCtor, subscribeVoice, TAB_ID, type Recognition } from './voice'

// "Jarvis" as the Thai recognizer tends to write it: จาร์วิส, จาวิส, จาร์วิด, จาวิก, Jarvis…
const NAME = '(?:j[ae]r?vi[sk]|จ[่้๊๋]?[าะ]?[่้๊๋]?(?:ร์|ร)?วิ[สซดทตชศษก](?:ต์)?)'
// Only "Hey Jarvis" / "เฮ้ จาร์วิส" wakes it, so just mentioning the name in conversation doesn't.
// Chrome sometimes hears "Hey Jarvis" as "Hey David", "เฮ้ เดวิด/เดวิก", "hang javis", "hen heavy", "เฮ้ยจาร์วิส".
const WAKE_WORD = new RegExp(`(?:hey|hang|hen|เฮ้ย|เฮ้|เฮ|เฮย์|เฮย)\\s*(?:${NAME}|d[ae]vi[dk]|heavy|เดวิ[ดก])`, 'i')
const MENTIONS_NAME = new RegExp(NAME, 'i')
const NAME_ONLY = new RegExp(`^\\s*${NAME}\\s*[.!?]?\\s*$`, 'i')
// "Stop Jarvis", "จาร์วิส หยุดการทำงาน": back to sleep.
const STOP_WORDS = /(?:หยุดการทำงาน|หยุดทำงาน|จบการทำงาน|หยุดฟัง|ปิดโหมดปลุก|\bstop\b|สต็อป|สต๊อป|สตอป)/i
// Awake, it goes back to sleep after this long without anything said to it (so a TV isn't taken as commands).
export const IDLE_SLEEP_MS = 60_000
// Act on what was said once the words stop for this long, so a pause mid-sentence doesn't cut a command short.
const SETTLE_MS = 3_500
const FATAL_ERRORS = new Set(['not-allowed', 'service-not-allowed', 'audio-capture'])

/** The command in a sentence that contains the wake word ("เฮ้ จาร์วิส เปิดไฟ" → "เปิดไฟ"), or null without it. */
export function findWakeWord(text: string): { command: string } | null {
  const m = WAKE_WORD.exec(text)
  if (!m) return null
  return { command: text.slice(m.index + m[0].length).replace(/^[\s,.!?]+/, '').trim() }
}

/** True for a stop phrase addressed to JARVIS (or said while it's awake). */
export function isStopCommand(text: string, awake: boolean): boolean {
  return STOP_WORDS.test(text) && (awake || MENTIONS_NAME.test(text))
}

interface Handlers {
  onCommand: (text: string) => void
  /** withCommand: the wake phrase already carried a command ("Hey Jarvis เปิดไฟ"), so no greeting is needed. */
  onAwake: (awake: boolean, bySpeech: boolean, withCommand: boolean) => void
  /** Woken by speech and nothing followed the wake phrase: answer it. */
  onGreet: () => void
  onHeard: (text: string) => void
  /** Every finished sentence the mic picked up, whether or not it was for JARVIS (shown for troubleshooting). */
  onFinal: (text: string) => void
  /** A recoverable problem (network, mic busy) to show, or null once it's working again. */
  onTrouble: (message: string | null) => void
  onFatal: (message: string) => void
}

/**
 * The mic in standby listens only for "Hey Jarvis". Once woken, every sentence is a command
 * (a continuous conversation) until "Stop Jarvis", the switch, or a minute of silence.
 * The browser ends recognition sessions on its own (silence, time limits, network), so it restarts until paused.
 */
class WakeListener {
  private rec: Recognition | null = null
  private awake = false
  private idle: number | undefined
  private settle: number | undefined
  // Finished sentences waiting for the speaker to stop (the pause may split one command into several).
  private pending = ''
  private interim = ''
  // Woken by speech just now: greet at the next flush unless a command came with it.
  private greet = false
  private running = false
  private restartDelay = 100
  private on: Handlers = { onCommand: () => {}, onAwake: () => {}, onGreet: () => {}, onHeard: () => {}, onFinal: () => {}, onTrouble: () => {}, onFatal: () => {} }

  /** Updated by the component on every render so commands go to the current conversation. */
  setHandlers(handlers: Handlers) {
    this.on = handlers
  }

  resume() {
    this.running = true
    if (this.awake) this.touch() // the idle clock counts from when JARVIS finished talking
    this.listen()
  }

  pause() {
    window.clearTimeout(this.settle)
    this.greet = false
    this.pending = ''
    this.interim = ''
    window.clearTimeout(this.idle)
    this.running = false
    this.rec?.abort()
    this.rec = null
    this.on.onHeard('')
  }

  setAwake(awake: boolean, bySpeech = false, withCommand = false) {
    window.clearTimeout(this.idle)
    if (awake) this.touch()
    if (awake === this.awake) return
    this.awake = awake
    this.on.onAwake(awake, bySpeech, withCommand)
  }

  private touch() {
    window.clearTimeout(this.idle)
    this.idle = window.setTimeout(() => this.setAwake(false, true), IDLE_SLEEP_MS)
  }

  private listen() {
    const Ctor = recognitionCtor()
    if (!Ctor || this.rec || !this.running) return
    const r = new Ctor()
    r.lang = LANG
    r.continuous = true
    r.interimResults = true
    r.onresult = (e) => {
      if (this.rec !== r) return // a session dropped by flush()
      window.clearTimeout(this.settle)
      let interim = ''
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const res = e.results[i]
        if (res.isFinal) {
          this.on.onFinal(res[0].transcript)
          this.pending = `${this.pending} ${res[0].transcript}`.trim()
        } else interim += res[0].transcript
      }
      this.interim = interim
      const said = `${this.pending} ${interim}`.trim()
      const wake = this.awake ? null : findWakeWord(said)
      if (wake && !isEcho(said)) {
        // Wake at once, on the first transcript that has the wake word: Chrome's final version of the
        // same words is often spelled differently ("เฮ จ๋าวิด") and would no longer match.
        this.pending = ''
        this.interim = ''
        this.dropSession()
        this.on.onHeard('')
        this.on.onFinal(said)
        this.greet = true
        this.setAwake(true, true, true)
        this.pending = wake.command
        this.settle = window.setTimeout(() => this.flush(), SETTLE_MS)
        return
      }
      if (said && this.isForUs(said)) {
        this.on.onHeard(said)
        this.settle = window.setTimeout(() => this.flush(), SETTLE_MS)
      } else {
        this.on.onHeard(interim)
        if (!interim) this.pending = '' // background talk, not for JARVIS
      }
    }
    r.onerror = (e) => {
      if (FATAL_ERRORS.has(e.error)) {
        this.running = false
        this.on.onFatal(ERRORS[e.error])
      } else if (e.error !== 'no-speech' && e.error !== 'aborted') {
        this.restartDelay = Math.min(this.restartDelay * 2, 10_000)
        this.on.onTrouble(ERRORS[e.error] ?? `ไมค์ขัดข้อง (${e.error}) กำลังลองใหม่`)
      }
      // 'no-speech' and 'aborted' are routine: onend restarts (or not, when paused).
    }
    r.onend = () => {
      if (this.rec !== r) return
      this.rec = null
      // Chrome can end a session during a pause; keep what was said so far for the next one.
      this.pending = `${this.pending} ${this.interim}`.trim()
      this.interim = ''
      if (!this.pending || !this.isForUs(this.pending)) {
        this.pending = ''
        this.on.onHeard('')
      }
      if (this.running) window.setTimeout(() => this.listen(), this.restartDelay)
    }
    this.rec = r
    try {
      r.start()
    } catch (err) {
      // e.g. the mic is still held by the previous session: try again shortly.
      this.rec = null
      this.on.onTrouble(`เริ่มฟังไม่ได้ (${(err as Error).name}) กำลังลองใหม่`)
      this.restartDelay = Math.min(this.restartDelay * 2, 10_000)
      if (this.running) window.setTimeout(() => this.listen(), this.restartDelay)
    }
  }

  /** Speech worth acting on before Chrome finalizes it: anything while awake, the wake word, or a stop phrase. */
  private isForUs(text: string) {
    return this.awake || findWakeWord(text) !== null || isStopCommand(text, false)
  }

  /** The speaker stopped: act on everything said, and drop this session so its late final result isn't handled twice. */
  private flush() {
    const text = `${this.pending} ${this.interim}`.trim()
    const greet = this.greet
    this.greet = false
    this.pending = ''
    this.interim = ''
    this.dropSession()
    this.on.onHeard('')
    if (text) {
      this.on.onFinal(text)
      this.handle(text)
    } else if (greet && this.awake) this.on.onGreet()
  }

  /** End the current recognition session without handling its late results, and start a fresh one. */
  private dropSession() {
    const r = this.rec
    if (!r) return
    this.rec = null
    r.abort()
    if (this.running) window.setTimeout(() => this.listen(), this.restartDelay)
  }

  private handle(transcript: string) {
    this.restartDelay = 100
    this.on.onTrouble(null)
    const text = transcript.trim()
    if (!text || isEcho(text)) return
    if (isStopCommand(text, this.awake)) {
      if (this.awake) this.setAwake(false, true)
      return
    }
    const wake = findWakeWord(text)
    if (!this.awake) {
      if (!wake) return
      const withCommand = wake.command.length >= 2
      this.setAwake(true, true, withCommand)
      if (withCommand) this.on.onCommand(wake.command)
      return
    }
    this.touch()
    // "Hey Jarvis" (or just the name) again while awake: nothing to send.
    if ((wake && wake.command.length < 2) || NAME_ONLY.test(text)) return
    this.on.onCommand(wake?.command || text)
  }
}

let audioCtx: AudioContext | null = null

/** A short rising "ding" when JARVIS wakes up; falling when it goes back to sleep. */
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
    // no audio output available; the status text still shows the state
  }
}

const STORAGE_KEY = 'jarvis.wake'

function loadMicOn(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === 'on'
  } catch {
    return false
  }
}

function saveMicOn(on: boolean) {
  try {
    localStorage.setItem(STORAGE_KEY, on ? 'on' : 'off')
  } catch {
    // not remembered across reloads; fine
  }
}

/**
 * Hands-free voice. micOn: the mic stays on waiting for "Hey Jarvis" (remembered across reloads).
 * awake: continuous conversation, turned on by "Hey Jarvis" or the switch and off by "Stop Jarvis".
 * Listening pauses while JARVIS is thinking or talking so it doesn't hear itself.
 */
export function useWakeWord(
  onCommand: (text: string) => void,
  paused: boolean,
  onAwakeChange: (awake: boolean, bySpeech: boolean, withCommand: boolean) => void = () => {},
  onGreet: () => void = () => {},
) {
  const [micOn, setMicOnState] = useState(loadMicOn)
  const [awake, setAwakeState] = useState(false)
  const [heard, setHeard] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [listener] = useState(() => new WakeListener())
  // The last sentence heard (for a few seconds) and any mic trouble, so it's clear what the mic is doing.
  const [lastHeard, setLastHeard] = useState('')
  const [trouble, setTrouble] = useState<string | null>(null)
  const [lastHeardTimer] = useState<{ id?: number }>(() => ({}))
  // Another dashboard tab is talking, or has taken the mic (only one tab listens at a time).
  const [otherTabSpeaking, setOtherTabSpeaking] = useState(false)
  const [otherTabHasMic, setOtherTabHasMic] = useState(false)

  useEffect(() => {
    let safety: number | undefined
    const unsubscribe = subscribeVoice((m) => {
      if (m.tab === TAB_ID) return
      if (m.type === 'listening') {
        setOtherTabHasMic(true)
        listener.setAwake(false)
      } else {
        setOtherTabSpeaking(m.on)
        window.clearTimeout(safety)
        // In case that tab closes mid-sentence and never says it finished.
        if (m.on) safety = window.setTimeout(() => setOtherTabSpeaking(false), 30_000)
      }
    })
    return () => {
      unsubscribe()
      window.clearTimeout(safety)
    }
  }, [listener])

  useEffect(() => {
    listener.setHandlers({
      onCommand,
      onAwake: (value, bySpeech, withCommand) => {
        chime(value ? 'up' : 'down')
        setAwakeState(value)
        onAwakeChange(value, bySpeech, withCommand)
      },
      onGreet,
      onHeard: (text) => {
        setHeard(text)
        if (text) setTrouble(null)
      },
      onFinal: (text) => {
        setLastHeard(text.trim())
        window.clearTimeout(lastHeardTimer.id)
        lastHeardTimer.id = window.setTimeout(() => setLastHeard(''), 6000)
      },
      onTrouble: setTrouble,
      onFatal: (message) => {
        setError(message)
        setMicOnState(false)
        saveMicOn(false)
      },
    })
  }, [listener, onCommand, onAwakeChange, onGreet, lastHeardTimer])

  const listening = micOn && !paused && !otherTabSpeaking && !otherTabHasMic
  useEffect(() => {
    if (listening) {
      broadcast({ type: 'listening' })
      listener.resume()
    } else listener.pause()
  }, [listening, listener])

  useEffect(() => () => listener.pause(), [listener])

  function setMicOn(on: boolean) {
    saveMicOn(on)
    setError(null)
    setOtherTabHasMic(false) // turning it on here takes the mic back from another tab
    setMicOnState(on)
    if (!on) listener.setAwake(false)
  }

  function setAwake(on: boolean) {
    if (on && (!micOn || otherTabHasMic)) setMicOn(true)
    listener.setAwake(on)
  }

  // What's being said to JARVIS right now (not background talk), for a live bubble in the chat.
  const speakingToJarvis = heard && (awake || findWakeWord(heard) !== null) ? heard : ''

  return { micOn, setMicOn, awake, setAwake, heard, lastHeard, trouble, speakingToJarvis, error, otherTabHasMic }
}
