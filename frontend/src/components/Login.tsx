import { useState, type FormEvent } from 'react'
import { api, setToken } from '../api'

export function Login({ onLogin }: { onLogin: () => void }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const { access_token } = await api.login(username, password)
      setToken(access_token)
      onLogin()
    } catch (err) {
      setError((err as Error).message === 'Invalid username or password' ? 'ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง' : (err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-full items-center justify-center px-4">
      <form onSubmit={submit} className="w-full max-w-sm space-y-4 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <div className="flex items-center gap-3">
          <img src="/favicon.svg" alt="" className="size-10" />
          <div>
            <h1 className="text-xl font-semibold">JARVIS</h1>
            <p className="text-sm text-slate-500">เข้าสู่ระบบเพื่อดูแลบ้าน</p>
          </div>
        </div>
        <label className="block space-y-1">
          <span className="text-sm font-medium">ชื่อผู้ใช้</span>
          <input
            className="w-full rounded-lg border border-slate-300 bg-transparent px-3 py-2 outline-none focus:border-sky-500 focus:ring-2 focus:ring-sky-500/30 dark:border-slate-700"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            autoFocus
            required
          />
        </label>
        <label className="block space-y-1">
          <span className="text-sm font-medium">รหัสผ่าน</span>
          <input
            type="password"
            className="w-full rounded-lg border border-slate-300 bg-transparent px-3 py-2 outline-none focus:border-sky-500 focus:ring-2 focus:ring-sky-500/30 dark:border-slate-700"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
          />
        </label>
        {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}
        <button
          disabled={busy}
          className="w-full rounded-lg bg-sky-600 py-2 font-medium text-white hover:bg-sky-700 disabled:opacity-60"
        >
          {busy ? 'กำลังเข้าสู่ระบบ…' : 'เข้าสู่ระบบ'}
        </button>
      </form>
    </div>
  )
}
