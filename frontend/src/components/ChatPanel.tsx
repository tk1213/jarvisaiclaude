import { useEffect, useRef, useState, type FormEvent } from 'react'
import { api, type ToolCall } from '../api'

interface Message {
  role: 'user' | 'jarvis' | 'error'
  text: string
  toolCalls?: ToolCall[]
}

const TOOL_LABELS: Record<string, string> = {
  get_devices: 'ดูรายการอุปกรณ์',
  get_device_status: 'อ่านสถานะ',
  control_device: 'สั่งอุปกรณ์',
  list_scenes: 'ดู scene',
  set_scene: 'สั่ง scene',
}

const SUGGESTIONS = ['มีอุปกรณ์อะไรบ้าง', 'ปลั๊ก 1 ใช้ไฟกี่วัตต์', 'ปิดทุกอย่างให้หน่อย']

export function ChatPanel() {
  const [messages, setMessages] = useState<Message[]>([])
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const bottom = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, busy])

  async function send(message: string) {
    const trimmed = message.trim()
    if (!trimmed || busy) return
    setText('')
    setMessages((m) => [...m, { role: 'user', text: trimmed }])
    setBusy(true)
    try {
      const res = await api.chat(trimmed, sessionId)
      setSessionId(res.session_id)
      setMessages((m) => [...m, { role: 'jarvis', text: res.reply, toolCalls: res.tool_calls }])
    } catch (e) {
      setMessages((m) => [...m, { role: 'error', text: (e as Error).message }])
    } finally {
      setBusy(false)
    }
  }

  function submit(e: FormEvent) {
    e.preventDefault()
    void send(text)
  }

  function reset() {
    setMessages([])
    setSessionId(null)
  }

  return (
    <section className="flex h-full min-h-[28rem] flex-col rounded-2xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
      <header className="flex items-center justify-between border-b border-slate-200 px-4 py-3 dark:border-slate-800">
        <h2 className="font-semibold">คุยกับ JARVIS</h2>
        {messages.length > 0 && (
          <button onClick={reset} className="text-sm text-slate-500 hover:text-slate-800 dark:hover:text-slate-200">
            เริ่มบทสนทนาใหม่
          </button>
        )}
      </header>

      <div className="flex-1 space-y-3 overflow-y-auto p-4">
        {messages.length === 0 && (
          <div className="space-y-3 text-sm text-slate-500">
            <p>สั่งงานบ้านได้ด้วยภาษาพูด เช่น</p>
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

      <form onSubmit={submit} className="flex gap-2 border-t border-slate-200 p-3 dark:border-slate-800">
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="พิมพ์คำสั่ง เช่น เปิดปลั๊ก 2"
          className="min-w-0 flex-1 rounded-lg border border-slate-300 bg-transparent px-3 py-2 outline-none focus:border-sky-500 focus:ring-2 focus:ring-sky-500/30 dark:border-slate-700"
        />
        <button disabled={busy || !text.trim()} className="rounded-lg bg-sky-600 px-4 font-medium text-white hover:bg-sky-700 disabled:opacity-50">
          ส่ง
        </button>
      </form>
    </section>
  )
}
