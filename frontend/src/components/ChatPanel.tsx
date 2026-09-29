import { useEffect, useRef, useState, type FormEvent } from 'react'
import { api, type ToolCall } from '../api'
import { setVoiceEngine, speak, stopSpeaking, sttSupported, useMissingThaiVoice, usesServerVoice, useSpeechRecognition } from '../voice'

interface Message {
  role: 'user' | 'jarvis' | 'error'
  text: string
  toolCalls?: ToolCall[]
}

const TOOL_LABELS: Record<string, string> = {
  get_devices: 'ดูรายการอุปกรณ์',
  get_device_status: 'อ่านสถานะ',
  control_device: 'สั่งอุปกรณ์',
  control_air_conditioner: 'สั่งแอร์',
  list_scenes: 'ดู scene',
  set_scene: 'สั่ง scene',
}

const SUGGESTIONS = ['มีอุปกรณ์อะไรบ้าง', 'ปลั๊ก 1 ใช้ไฟกี่วัตต์', 'ปิดทุกอย่างให้หน่อย']

export function ChatPanel() {
  const [messages, setMessages] = useState<Message[]>([])
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [speaking, setSpeaking] = useState(false)
  const [voiceNotice, setVoiceNotice] = useState<string | null>(null)
  const bottom = useRef<HTMLDivElement>(null)
  const mic = useSpeechRecognition((heard) => void send(heard, 'voice'))
  const missingThaiVoice = useMissingThaiVoice()

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, busy])

  useEffect(() => stopSpeaking, [])

  useEffect(() => {
    api
      .voiceConfig()
      .then((c) => setVoiceEngine(c.engine))
      .catch(() => {
        // Old server without /voice: speak() still tries it and falls back on its own.
      })
  }, [])

  async function send(message: string, channel: 'dashboard' | 'voice' = 'dashboard') {
    const trimmed = message.trim()
    if (!trimmed || busy) return
    setText('')
    setMessages((m) => [...m, { role: 'user', text: trimmed }])
    setBusy(true)
    try {
      const res = await api.chat(trimmed, sessionId, channel)
      setSessionId(res.session_id)
      setMessages((m) => [...m, { role: 'jarvis', text: res.reply, toolCalls: res.tool_calls }])
      // A spoken question gets a spoken answer.
      if (channel === 'voice') {
        setSpeaking(true)
        speak(
          res.reply,
          () => setSpeaking(false),
          (reason) => setVoiceNotice(reason),
        )
      }
    } catch (e) {
      setMessages((m) => [...m, { role: 'error', text: (e as Error).message }])
    } finally {
      setBusy(false)
    }
  }

  function toggleMic() {
    if (mic.listening) return mic.stop()
    // Talking over JARVIS interrupts it.
    stopSpeaking()
    setSpeaking(false)
    mic.start()
  }

  function quiet() {
    stopSpeaking()
    setSpeaking(false)
  }

  function submit(e: FormEvent) {
    e.preventDefault()
    void send(text)
  }

  function reset() {
    quiet()
    setMessages([])
    setSessionId(null)
  }

  return (
    <section className="flex h-full min-h-[28rem] flex-col rounded-2xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
      <header className="flex items-center justify-between border-b border-slate-200 px-4 py-3 dark:border-slate-800">
        <h2 className="font-semibold">คุยกับ JARVIS</h2>
        <div className="flex items-center gap-3">
          {speaking && (
            <button onClick={quiet} className="text-sm text-sky-700 hover:text-sky-900 dark:text-sky-300 dark:hover:text-sky-100">
              หยุดพูด
            </button>
          )}
          {messages.length > 0 && (
            <button onClick={reset} className="text-sm text-slate-500 hover:text-slate-800 dark:hover:text-slate-200">
              เริ่มบทสนทนาใหม่
            </button>
          )}
        </div>
      </header>

      <div className="flex-1 space-y-3 overflow-y-auto p-4">
        {messages.length === 0 && (
          <div className="space-y-3 text-sm text-slate-500">
            <p>{sttSupported ? 'พิมพ์ หรือกดไมค์แล้วพูดสั่งงานบ้านได้เลย เช่น' : 'สั่งงานบ้านได้ด้วยภาษาพูด เช่น'}</p>
            <div className="flex flex-wrap gap-2">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  onClick={() => void send(s)}
                  className="rounded-full border border-slate-300 px-3 py-1 hover:border-sky-500 hover:text-sky-700 dark:border-slate-700 dark:hover:text-sky-300"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((m, i) => (
          <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div
              className={`max-w-[85%] rounded-2xl px-3.5 py-2 whitespace-pre-wrap ${
                m.role === 'user'
                  ? 'bg-sky-600 text-white'
                  : m.role === 'error'
                    ? 'bg-red-50 text-red-700 dark:bg-red-950/50 dark:text-red-300'
                    : 'bg-slate-100 dark:bg-slate-800'
              }`}
            >
              {m.toolCalls && m.toolCalls.length > 0 && (
                <div className="mb-1.5 flex flex-wrap gap-1">
                  {m.toolCalls.map((t, j) => (
                    <span
                      key={j}
                      className={`rounded-full px-2 py-0.5 text-xs ${
                        t.ok ? 'bg-slate-200 text-slate-600 dark:bg-slate-700 dark:text-slate-300' : 'bg-red-100 text-red-700 dark:bg-red-900/50 dark:text-red-300'
                      }`}
                    >
                      {TOOL_LABELS[t.name] ?? t.name}
                    </span>
                  ))}
                </div>
              )}
              {m.text}
            </div>
          </div>
        ))}

        {busy && (
          <div className="flex justify-start">
            <div className="rounded-2xl bg-slate-100 px-3.5 py-2 text-slate-500 dark:bg-slate-800">JARVIS กำลังคิด…</div>
          </div>
        )}
        <div ref={bottom} />
      </div>

      {voiceNotice && (
        <div role="status" className="flex items-start gap-2 border-t border-slate-200 px-4 py-2 text-xs text-amber-800 dark:border-slate-800 dark:text-amber-300">
          <p className="flex-1">
            ใช้เสียงสำรองของเบราว์เซอร์อยู่ เพราะเสียงผู้หญิงจาก server ใช้ไม่ได้ ({voiceNotice}) ลองปิดแล้วเปิด start.bat ใหม่
          </p>
          <button onClick={() => setVoiceNotice(null)} aria-label="ปิดข้อความ" className="shrink-0 hover:text-amber-950 dark:hover:text-amber-100">
            ✕
          </button>
        </div>
      )}

      {(mic.error || (speaking && missingThaiVoice && !usesServerVoice())) && (
        <p role="alert" className="border-t border-slate-200 px-4 py-2 text-xs text-amber-800 dark:border-slate-800 dark:text-amber-300">
          {mic.error ?? 'เครื่องนี้ไม่มีเสียงอ่านภาษาไทย ตั้ง TTS_ENGINE=edge ใน .env หรือเปิดด้วย Microsoft Edge'}
        </p>
      )}

      <form onSubmit={submit} className="flex gap-2 border-t border-slate-200 p-3 dark:border-slate-800">
        <input
          value={mic.listening ? mic.interim : text}
          onChange={(e) => setText(e.target.value)}
          readOnly={mic.listening}
          placeholder={mic.listening ? 'กำลังฟัง… พูดได้เลย' : 'พิมพ์คำสั่ง เช่น เปิดปลั๊ก 2'}
          className="min-w-0 flex-1 rounded-lg border border-slate-300 bg-transparent px-3 py-2 outline-none focus:border-sky-500 focus:ring-2 focus:ring-sky-500/30 dark:border-slate-700"
        />
        <button
          type="button"
          onClick={toggleMic}
          disabled={!sttSupported || busy}
          aria-pressed={mic.listening}
          aria-label={mic.listening ? 'หยุดฟัง' : 'พูดสั่งงาน'}
          title={sttSupported ? (mic.listening ? 'หยุดฟัง' : 'พูดสั่งงาน') : 'เบราว์เซอร์นี้ไม่รองรับการพูด ใช้ Chrome หรือ Edge'}
          className={`grid size-10 shrink-0 place-items-center rounded-lg transition-colors disabled:opacity-40 ${
            mic.listening
              ? 'animate-pulse bg-red-600 text-white hover:bg-red-700'
              : 'border border-slate-300 text-slate-600 hover:border-sky-500 hover:text-sky-700 dark:border-slate-700 dark:text-slate-300 dark:hover:text-sky-300'
          }`}
        >
          <svg viewBox="0 0 20 20" fill="currentColor" className="size-5" aria-hidden="true">
            <path d="M10 2a3 3 0 0 0-3 3v5a3 3 0 1 0 6 0V5a3 3 0 0 0-3-3Z" />
            <path d="M5 9.5a.75.75 0 0 0-1.5 0 6.5 6.5 0 0 0 5.75 6.46V17.5H7.5a.75.75 0 0 0 0 1.5h5a.75.75 0 0 0 0-1.5h-1.75v-1.54A6.5 6.5 0 0 0 16.5 9.5a.75.75 0 0 0-1.5 0 5 5 0 0 1-10 0Z" />
          </svg>
        </button>
        <button disabled={busy || mic.listening || !text.trim()} className="rounded-lg bg-sky-600 px-4 font-medium text-white hover:bg-sky-700 disabled:opacity-50">
          ส่ง
        </button>
      </form>
    </section>
  )
}
