import { useEffect, useRef, useState, type FormEvent } from 'react'
import { api, type ToolCall } from '../api'
import { chime, useWakeWord } from '../wake'
import {
  getVoiceGender,
  setVoiceEngine,
  setVoiceGender,
  speak,
  stopSpeaking,
  sttSupported,
  useMissingThaiVoice,
  useSpeechRecognition,
  usesServerVoice,
  type VoiceGender,
} from '../voice'

interface Message {
  // 'note': a local status line (JARVIS woke up / went to sleep), never sent anywhere.
  role: 'user' | 'jarvis' | 'error' | 'note'
  text: string
  toolCalls?: ToolCall[]
  // Pictures sent with a user message (small JPEG data URLs), shown in its bubble.
  pictures?: string[]
}

const MAX_PICTURES = 4
const PICTURE_SIDE = 1024

/** A picture file as a JPEG data URL no larger than PICTURE_SIDE: a phone photo becomes ~100-200 KB to upload. */
async function shrinkPicture(file: File): Promise<string> {
  const bitmap = await createImageBitmap(file)
  const scale = Math.min(1, PICTURE_SIDE / Math.max(bitmap.width, bitmap.height))
  const canvas = document.createElement('canvas')
  canvas.width = Math.round(bitmap.width * scale)
  canvas.height = Math.round(bitmap.height * scale)
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('เบราว์เซอร์นี้ย่อรูปไม่ได้')
  ctx.fillStyle = '#fff' // transparent PNGs: white, not black, behind the text
  ctx.fillRect(0, 0, canvas.width, canvas.height)
  ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height)
  bitmap.close()
  return canvas.toDataURL('image/jpeg', 0.85)
}

const TOOL_LABELS: Record<string, string> = {
  get_devices: 'ดูรายการอุปกรณ์',
  get_device_status: 'อ่านสถานะ',
  control_device: 'สั่งอุปกรณ์',
  control_air_conditioner: 'สั่งแอร์',
  list_scenes: 'ดู scene',
  set_scene: 'สั่ง scene',
  web_search: 'ค้นเว็บ',
  send_to_line: 'ส่งเข้า LINE',
  find_customers: 'ค้นลูกค้า',
  find_products: 'ค้นสินค้า',
  save_product_set: 'บันทึกชุดสินค้า',
  get_product_set: 'ใช้ชุดสินค้า',
  set_product_set_remarks: 'แก้หมายเหตุชุด',
  list_product_sets: 'ดูชุดสินค้า',
  delete_product_set: 'ลบชุดสินค้า',
  last_order: 'ดูออเดอร์ล่าสุด',
  prepare_document: 'ร่างเอกสาร',
  issue_document: 'ออกเอกสาร',
  cancel_document: 'ยกเลิกเอกสาร',
  list_documents: 'ดูเอกสาร',
}

// The answers offered under a document draft (the same buttons as on LINE); a quotation with VAT can also drop it.
const CONFIRM_CHOICES = ['OK', 'Cancel']
const NO_VAT = 'ไม่เอาแวท'

function confirmChoices(toolCalls: ToolCall[] | undefined): string[] {
  const draft = toolCalls?.filter((t) => t.ok && t.name === 'prepare_document').at(-1)
  if (!draft) return []
  return draft.input.doc_type === 'quotation' && draft.input.vat === true ? [...CONFIRM_CHOICES, NO_VAT] : CONFIRM_CHOICES
}

const GREETING = { female: 'ค่ะ TK มีอะไรให้ช่วยไหมคะ', male: 'ครับ TK มีอะไรให้ช่วยไหมครับ' }

const SUGGESTIONS = ['มีอุปกรณ์อะไรบ้าง', 'ปลั๊ก 1 ใช้ไฟกี่วัตต์', 'ปิดทุกอย่างให้หน่อย']
// The FlowAccount page's starters fill the box instead of sending: the customer's name still has to be added.
const SET_SUGGESTIONS = ['A', 'B', 'C', 'D'].map((s) => `ออกใบเสนอราคา ชุด ${s} ให้ `)

/**
 * onDocuments: JARVIS just drafted or issued a document (the dashboard's list refreshes).
 * page: which dashboard page is showing, for the example commands.
 */
export function ChatPanel({ onDocuments, page = 'home' }: { onDocuments?: () => void; page?: 'home' | 'flowaccount' }) {
  const [messages, setMessages] = useState<Message[]>([])
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [text, setText] = useState('')
  const input = useRef<HTMLInputElement>(null)
  // Pictures waiting to go with the next message.
  const [pictures, setPictures] = useState<string[]>([])
  const picker = useRef<HTMLInputElement>(null)
  const [pictureError, setPictureError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [speaking, setSpeaking] = useState(false)
  const [voiceNotice, setVoiceNotice] = useState<string | null>(null)
  const [voiceGender, setGender] = useState<VoiceGender>(getVoiceGender)
  const bottom = useRef<HTMLDivElement>(null)
  const mic = useSpeechRecognition((heard) => void send(heard, 'voice'))
  const missingThaiVoice = useMissingThaiVoice()
  // Hands-free: listens for "Hey Jarvis", but not while JARVIS thinks or talks (it would hear itself).
  const wake = useWakeWord(
    (command) => void send(command, 'voice'),
    busy || speaking || mic.listening,
    (awake, bySpeech) => {
      const text = awake
        ? '🔔 โหมดปลุกเปิดแล้ว พูดคำสั่งต่อเนื่องได้เลย (พูด "Stop Jarvis" เพื่อพัก)'
        : bySpeech
          ? '💤 JARVIS พักแล้ว เรียก "Hey Jarvis" เพื่อปลุก'
          : '💤 ปิดโหมดปลุกแล้ว'
      setMessages((m) => [...m, { role: 'note', text }])
    },
    // Answer a bare "Hey Jarvis" locally, without a round trip to Claude.
    () => say(GREETING[getVoiceGender()]),
  )

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, busy, wake.speakingToJarvis])

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
    const attached = pictures
    setText('')
    setPictures([])
    setPictureError(null)
    setMessages((m) => [...m, { role: 'user', text: trimmed, pictures: attached.length ? attached : undefined }])
    setBusy(true)
    try {
      const res = await api.chat(trimmed, sessionId, channel, getVoiceGender(), attached)
      setSessionId(res.session_id)
      setMessages((m) => [...m, { role: 'jarvis', text: res.reply, toolCalls: res.tool_calls }])
      if (res.tool_calls.some((t) => t.name.endsWith('_document') || t.name.includes('product_set'))) onDocuments?.()
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

  async function addPictures(files: FileList | null) {
    setPictureError(null)
    const chosen = Array.from(files ?? []).filter((f) => f.type.startsWith('image/'))
    if (pictures.length + chosen.length > MAX_PICTURES) setPictureError(`แนบได้ครั้งละ ${MAX_PICTURES} รูป`)
    try {
      const shrunk = await Promise.all(chosen.slice(0, MAX_PICTURES - pictures.length).map(shrinkPicture))
      setPictures((current) => [...current, ...shrunk].slice(0, MAX_PICTURES))
    } catch {
      setPictureError('เปิดรูปไม่ได้ ลองเลือกรูปอื่น')
    }
    if (picker.current) picker.current.value = ''
  }

  /** A reply JARVIS gives locally (no Claude call), shown and spoken like any other. */
  function say(text: string) {
    setMessages((m) => [...m, { role: 'jarvis', text }])
    setSpeaking(true)
    speak(
      text,
      () => setSpeaking(false),
      (reason) => setVoiceNotice(reason),
    )
  }

  function toggleMic() {
    if (mic.listening) return mic.stop()
    // Talking over JARVIS interrupts it.
    stopSpeaking()
    setSpeaking(false)
    if (wake.micOn) {
      // The hands-free listener is already running; the button just wakes it up.
      wake.setAwake(true)
      return
    }
    mic.start()
  }

  function toggleStandby() {
    if (!wake.micOn || wake.otherTabHasMic) chime() // also unlocks audio so later chimes can play
    // While another dashboard tab has the mic, the button takes it back for this tab.
    wake.setMicOn(!wake.micOn || wake.otherTabHasMic)
  }

  const wakeStatus = wake.otherTabHasMic
    ? 'ไมค์ถูกใช้อยู่ใน Dashboard อีกแท็บ กดปุ่ม 🎙 เพื่อใช้แท็บนี้แทน'
    : speaking
      ? 'JARVIS กำลังพูด… กดไมค์เพื่อพูดแทรก'
      : busy
        ? 'JARVIS กำลังคิด…'
        : wake.awake
          ? 'โหมดปลุก: ฟังอยู่ พูดคำสั่งได้เลย ("Stop Jarvis" เพื่อพัก)'
          : 'ไมค์รอคำว่า "Hey Jarvis" / "เฮ้ จาร์วิส"'
  const listeningLive = wake.awake && !busy && !speaking
  // OK / Cancel (/ ไม่เอาแวท) only under the latest reply, and only when that reply made a document draft.
  const last = messages[messages.length - 1]
  const choices = !busy && last?.role === 'jarvis' ? confirmChoices(last.toolCalls) : []

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
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 px-4 py-3 dark:border-slate-800">
        <h2 className="font-semibold">คุยกับ JARVIS</h2>
        <div className="flex flex-wrap items-center gap-3 whitespace-nowrap">
          {sttSupported && (
            <>
              <button
                aria-pressed={wake.micOn}
                onClick={toggleStandby}
                title={wake.micOn ? 'ปิดไมค์ (เลิกรอคำว่า Hey Jarvis)' : 'เปิดไมค์รอคำว่า Hey Jarvis'}
                className={`rounded-full px-2 py-0.5 text-xs transition-colors ${
                  wake.micOn
                    ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/50 dark:text-emerald-200'
                    : 'bg-slate-100 text-slate-500 hover:text-slate-800 dark:bg-slate-800 dark:hover:text-slate-200'
                }`}
              >
                {wake.otherTabHasMic ? '🎙 ใช้อยู่แท็บอื่น' : wake.micOn ? '🎙 รอ Hey Jarvis' : '🎙 เปิดไมค์รอเรียก'}
              </button>
              <button
                role="switch"
                aria-checked={wake.awake}
                onClick={() => wake.setAwake(!wake.awake)}
                title='คุยต่อเนื่องโดยไม่ต้องเรียกชื่อ เปิดด้วยคำว่า "Hey Jarvis" ปิดด้วย "Stop Jarvis"'
                className="flex items-center gap-1.5 text-sm text-slate-500 hover:text-slate-800 dark:hover:text-slate-200"
              >
                <span className={`relative h-4 w-7 rounded-full transition-colors ${wake.awake ? 'bg-sky-600' : 'bg-slate-300 dark:bg-slate-700'}`}>
                  <span className={`absolute top-0.5 left-0.5 size-3 rounded-full bg-white transition-transform ${wake.awake ? 'translate-x-3' : ''}`} />
                </span>
                โหมดปลุก
              </button>
            </>
          )}
          <button
            onClick={() => {
              const next = voiceGender === 'female' ? 'male' : 'female'
              setVoiceGender(next)
              setGender(next)
            }}
            title="เลือกเสียงที่จาร์วิสใช้ตอบ"
            className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600 hover:text-slate-900 dark:bg-slate-800 dark:text-slate-300 dark:hover:text-white"
          >
            {voiceGender === 'female' ? '🔊 เสียงผู้หญิง' : '🔊 เสียงผู้ชาย'}
          </button>
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
            {page === 'flowaccount' ? (
              <p>เลือกชุดสินค้า แล้วพิมพ์ชื่อลูกค้าต่อท้ายก่อนกดส่ง</p>
            ) : (
              <p>{sttSupported ? 'พิมพ์ หรือกดไมค์แล้วพูดสั่งงานบ้านได้เลย เช่น' : 'สั่งงานบ้านได้ด้วยภาษาพูด เช่น'}</p>
            )}
            {page === 'home' && sttSupported && !wake.micOn && <p>อยากเรียกด้วยเสียง "Hey Jarvis" กดปุ่ม 🎙 เปิดไมค์รอเรียก ด้านบนก่อน</p>}
            <div className="flex flex-wrap gap-2">
              {page === 'flowaccount' &&
                SET_SUGGESTIONS.map((s) => (
                  <button
                    key={s}
                    onClick={() => {
                      setText(s)
                      input.current?.focus()
                    }}
                    className="rounded-full border border-slate-300 px-3 py-1 hover:border-sky-500 hover:text-sky-700 dark:border-slate-700 dark:hover:text-sky-300"
                  >
                    {s.replace('ออกใบเสนอราคา ', 'ใบเสนอราคา ').replace(' ให้ ', '')}
                  </button>
                ))}
              {page === 'home' &&
                SUGGESTIONS.map((s) => (
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

        {messages.map((m, i) =>
          m.role === 'note' ? (
            <p key={i} className="text-center text-xs text-slate-500">
              {m.text}
            </p>
          ) : (
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
                {m.pictures && (
                  <div className="mb-1.5 flex flex-wrap justify-end gap-1">
                    {m.pictures.map((src, j) => (
                      <img key={j} src={src} alt={`รูปที่ ${j + 1}`} className="size-16 rounded-lg object-cover" />
                    ))}
                  </div>
                )}
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
          ),
        )}

        {choices.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {choices.map((choice) => (
              <button
                key={choice}
                onClick={() => void send(choice)}
                className={`rounded-full px-5 py-1.5 text-sm font-medium transition-colors ${
                  choice === 'OK'
                    ? 'bg-sky-600 text-white hover:bg-sky-700'
                    : 'border border-slate-300 text-slate-700 hover:border-red-400 hover:text-red-700 dark:border-slate-700 dark:text-slate-200 dark:hover:text-red-300'
                }`}
              >
                {choice}
              </button>
            ))}
          </div>
        )}

        {wake.micOn && wake.speakingToJarvis && !busy && (
          <div className="flex justify-end">
            <div className="max-w-[85%] rounded-2xl border border-dashed border-sky-400 px-3.5 py-2 text-sky-800 dark:border-sky-600 dark:text-sky-200">
              {wake.speakingToJarvis}…
            </div>
          </div>
        )}

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
            เสียง{voiceGender === 'female' ? 'ผู้หญิง' : 'ผู้ชาย'}จาก server ใช้ไม่ได้ ({voiceNotice}) คำตอบจึงแสดงเป็นข้อความอย่างเดียว ลองปิดแล้วเปิด start.bat ใหม่
          </p>
          <button onClick={() => setVoiceNotice(null)} aria-label="ปิดข้อความ" className="shrink-0 hover:text-amber-950 dark:hover:text-amber-100">
            ✕
          </button>
        </div>
      )}

      {wake.micOn && (
        <div aria-live="polite" className="flex items-center gap-2 border-t border-slate-200 px-4 py-2 text-xs dark:border-slate-800">
          <span className={`size-2 shrink-0 rounded-full ${listeningLive ? 'animate-pulse bg-red-500' : busy || speaking ? 'bg-slate-400' : 'bg-emerald-500'}`} />
          <span className={listeningLive ? 'font-medium text-red-700 dark:text-red-300' : 'text-slate-500'}>{wakeStatus}</span>
          {wake.trouble ? (
            <span className="min-w-0 truncate text-amber-700 dark:text-amber-300">{wake.trouble}</span>
          ) : (
            (wake.heard || wake.lastHeard) && <span className="min-w-0 truncate text-slate-400">ได้ยิน: “{wake.heard || wake.lastHeard}”</span>
          )}
        </div>
      )}

      {(mic.error || wake.error || (speaking && missingThaiVoice && !usesServerVoice())) && (
        <p role="alert" className="border-t border-slate-200 px-4 py-2 text-xs text-amber-800 dark:border-slate-800 dark:text-amber-300">
          {mic.error ?? wake.error ?? 'เครื่องนี้ไม่มีเสียงอ่านภาษาไทย ตั้ง TTS_ENGINE=edge ใน .env หรือเปิดด้วย Microsoft Edge'}
        </p>
      )}

      {(pictures.length > 0 || pictureError) && (
        <div className="flex flex-wrap items-center gap-2 border-t border-slate-200 px-3 pt-3 dark:border-slate-800">
          {pictures.map((src, i) => (
            <div key={i} className="relative">
              <img src={src} alt={`รูปที่แนบ ${i + 1}`} className="size-14 rounded-lg border border-slate-300 object-cover dark:border-slate-700" />
              <button
                type="button"
                onClick={() => setPictures(pictures.filter((_, j) => j !== i))}
                aria-label={`เอารูปที่ ${i + 1} ออก`}
                className="absolute -top-1.5 -right-1.5 grid size-5 place-items-center rounded-full bg-slate-700 text-xs text-white hover:bg-red-600"
              >
                ✕
              </button>
            </div>
          ))}
          {pictures.length > 0 && <span className="text-xs text-slate-500">พิมพ์คำสั่งแล้วกดส่ง รูปจะส่งไปพร้อมข้อความ</span>}
          {pictureError && <span className="text-xs text-amber-700 dark:text-amber-300">{pictureError}</span>}
        </div>
      )}

      <form onSubmit={submit} className="flex gap-2 border-t border-slate-200 p-3 dark:border-slate-800">
        <input ref={picker} type="file" accept="image/*" multiple hidden onChange={(e) => void addPictures(e.target.files)} />
        <button
          type="button"
          onClick={() => picker.current?.click()}
          disabled={busy || pictures.length >= MAX_PICTURES}
          aria-label="แนบรูป"
          title={`แนบรูป (สูงสุด ${MAX_PICTURES} รูป) เช่น นามบัตรหรือที่อยู่ลูกค้า`}
          className="grid size-10 shrink-0 place-items-center rounded-lg border border-slate-300 text-lg text-slate-600 transition-colors hover:border-sky-500 hover:text-sky-700 disabled:opacity-40 dark:border-slate-700 dark:text-slate-300 dark:hover:text-sky-300"
        >
          📎
        </button>
        <input
          ref={input}
          value={mic.listening ? mic.interim : text}
          onChange={(e) => setText(e.target.value)}
          readOnly={mic.listening}
          placeholder={mic.listening ? 'กำลังฟัง… พูดได้เลย' : page === 'flowaccount' ? 'พิมพ์คำสั่ง เช่น ออกใบเสนอราคา ชุด A ให้บริษัท เอ' : 'พิมพ์คำสั่ง เช่น เปิดปลั๊ก 2'}
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
