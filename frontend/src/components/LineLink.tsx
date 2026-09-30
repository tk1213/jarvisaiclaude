import { useEffect, useState } from 'react'
import { api, type LineStatus } from '../api'

/** Header button: link this account to the LINE Official Account with a one-time code. */
export function LineLink() {
  const [open, setOpen] = useState(false)
  const [status, setStatus] = useState<LineStatus | null>(null)
  const [code, setCode] = useState<{ value: string; until: number } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    api.lineStatus().then(setStatus, () => setStatus(null))
  }, [])

  // Count the code down, and notice when the LINE side has used it.
  useEffect(() => {
    if (!open || !code) return
    const timer = window.setInterval(() => {
      setNow(Date.now())
      api.lineStatus().then((s) => {
        setStatus(s)
        if (s.linked) setCode(null)
      }, () => {})
    }, 3000)
    return () => window.clearInterval(timer)
  }, [open, code])

  async function newCode() {
    setError(null)
    try {
      const c = await api.lineLinkCode()
      const at = Date.now()
      setNow(at)
      setCode({ value: c.code, until: at + c.expires_in * 1000 })
    } catch (e) {
      setError((e as Error).message)
    }
  }

  async function unlink() {
    setError(null)
    try {
      await api.lineUnlink()
      setStatus((s) => (s ? { ...s, linked: false } : s))
    } catch (e) {
      setError((e as Error).message)
    }
  }

  if (!status) return null
  const secondsLeft = code ? Math.max(0, Math.round((code.until - now) / 1000)) : 0

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className="flex items-center gap-1.5 rounded-lg border border-slate-300 px-3 py-1.5 hover:border-emerald-500 dark:border-slate-700"
      >
        <span className={`size-2 rounded-full ${status.linked ? 'bg-emerald-500' : 'bg-slate-400'}`} />
        LINE
      </button>
      {open && (
        <div className="absolute right-0 z-10 mt-2 w-72 space-y-3 rounded-xl border border-slate-200 bg-white p-4 text-sm shadow-lg dark:border-slate-700 dark:bg-slate-900">
          {!status.configured ? (
            <p className="text-slate-600 dark:text-slate-300">
              ยังไม่ได้ตั้งค่า LINE ใส่ <code>LINE_CHANNEL_SECRET</code> และ <code>LINE_CHANNEL_ACCESS_TOKEN</code> ใน <code>backend\.env</code> แล้วเปิด start.bat ใหม่
            </p>
          ) : status.linked ? (
            <>
              <p className="text-emerald-700 dark:text-emerald-300">เชื่อม LINE แล้ว สั่งงานจาร์วิสในแชท LINE OA ได้เลย</p>
              <button onClick={() => void unlink()} className="text-xs text-slate-500 underline hover:text-red-600">
                ยกเลิกการเชื่อม
              </button>
            </>
          ) : code && secondsLeft > 0 ? (
            <>
              <p className="text-slate-600 dark:text-slate-300">ส่งรหัสนี้ในแชท LINE OA ของจาร์วิส</p>
              <p className="text-center font-mono text-3xl font-semibold tracking-[0.3em]">{code.value}</p>
              <p className="text-center text-xs text-slate-500">
                หมดอายุใน {Math.floor(secondsLeft / 60)}:{String(secondsLeft % 60).padStart(2, '0')} นาที
              </p>
            </>
          ) : (
            <>
              <p className="text-slate-600 dark:text-slate-300">เพิ่มเพื่อน LINE OA ของจาร์วิส แล้วขอรหัสเพื่อเชื่อมบัญชีนี้</p>
              <button onClick={() => void newCode()} className="w-full rounded-lg bg-emerald-600 px-3 py-2 font-medium text-white hover:bg-emerald-700">
                ขอรหัสเชื่อม LINE
              </button>
            </>
          )}
          {error && <p className="text-xs text-red-600">{error}</p>}
        </div>
      )}
    </div>
  )
}
