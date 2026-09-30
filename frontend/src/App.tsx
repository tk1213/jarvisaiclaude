import { useEffect, useState } from 'react'
import { api, getToken, setToken, type User } from './api'
import { ChatPanel } from './components/ChatPanel'
import { DeviceCard } from './components/DeviceCard'
import { Documents } from './components/Documents'
import { LineLink } from './components/LineLink'
import { Login } from './components/Login'
import { Scenes } from './components/Scenes'
import { powerCode } from './readings'
import { useDevices, type LinkState } from './useDevices'

const LINK_LABEL: Record<LinkState, { text: string; dot: string }> = {
  live: { text: 'เชื่อมต่อสด', dot: 'bg-emerald-500' },
  connecting: { text: 'กำลังเชื่อมต่อ…', dot: 'bg-amber-400' },
  offline: { text: 'ขาดการเชื่อมต่อ', dot: 'bg-red-500' },
}

export default function App() {
  const [loggedIn, setLoggedIn] = useState(() => getToken() !== null)

  useEffect(() => {
    const onLogout = () => setLoggedIn(false)
    window.addEventListener('jarvis:logout', onLogout)
    return () => window.removeEventListener('jarvis:logout', onLogout)
  }, [])

  if (!loggedIn) return <Login onLogin={() => setLoggedIn(true)} />
  return (
    <Dashboard
      onLogout={() => {
        setToken(null)
        setLoggedIn(false)
      }}
    />
  )
}

function Dashboard({ onLogout }: { onLogout: () => void }) {
  const { devices, link, error, upsert, setDevices } = useDevices()
  const [user, setUser] = useState<User | null>(null)
  const [syncing, setSyncing] = useState(false)
  const [syncError, setSyncError] = useState<string | null>(null)
  const [syncNote, setSyncNote] = useState<string | null>(null)
  const [documentsVersion, setDocumentsVersion] = useState(0)

  useEffect(() => {
    api.me().then(setUser, () => {})
  }, [])

  async function sync() {
    setSyncing(true)
    setSyncError(null)
    setSyncNote(null)
    try {
      const before = new Map(devices.map((d) => [d.tuya_device_id, d.name]))
      const after = await api.sync()
      const added = after.filter((d) => !before.has(d.tuya_device_id)).map((d) => d.name)
      const kept = new Set(after.map((d) => d.tuya_device_id))
      const removed = [...before].filter(([id]) => !kept.has(id)).map(([, name]) => name)
      setDevices(after)
      const parts = []
      if (added.length) parts.push(`เพิ่ม ${added.join(', ')}`)
      if (removed.length) parts.push(`นำออก ${removed.join(', ')} (ไม่อยู่ในบัญชี Tuya แล้ว)`)
      setSyncNote(parts.length ? `อัปเดตแล้ว: ${parts.join(' · ')}` : 'อัปเดตแล้ว ไม่มีอุปกรณ์ใหม่')
    } catch (e) {
      setSyncError((e as Error).message)
    } finally {
      setSyncing(false)
    }
  }

  const canControl = user?.can_control_devices ?? false
  const onCount = devices.filter((d) => {
    const code = powerCode(d.status)
    return code !== null && d.status[code] === true
  }).length
  const status = LINK_LABEL[link]
  const rooms = [...new Set(devices.map((d) => d.room).filter((r): r is string => !!r))].sort((a, b) => a.localeCompare(b, 'th'))
  // Group by room once any room is set; devices without one go last.
  const groups: [string | null, typeof devices][] = rooms.length
    ? [...rooms.map((r) => [r, devices.filter((d) => d.room === r)] as [string, typeof devices]), [null, devices.filter((d) => !d.room)]]
    : [[null, devices]]
  const shownError = syncError ?? error

  return (
    <div className="mx-auto flex min-h-full max-w-7xl flex-col gap-6 px-4 py-5 sm:px-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <img src="/favicon.svg" alt="" className="size-9" />
          <div>
            <h1 className="text-lg leading-tight font-semibold">JARVIS</h1>
            <p className="flex items-center gap-1.5 text-xs text-slate-500">
              <span className={`size-2 rounded-full ${status.dot}`} />
              {status.text}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2 text-sm">
          {user && <span className="hidden text-slate-500 sm:inline">{user.display_name}</span>}
          <LineLink />
          <button
            onClick={() => void sync()}
            disabled={syncing}
            className="rounded-lg border border-slate-300 px-3 py-1.5 hover:border-sky-500 disabled:opacity-50 dark:border-slate-700"
          >
            {syncing ? 'กำลังอัปเดต…' : 'อัปเดตอุปกรณ์'}
          </button>
          <button onClick={onLogout} className="rounded-lg px-3 py-1.5 text-slate-500 hover:bg-slate-200 dark:hover:bg-slate-800">
            ออกจากระบบ
          </button>
        </div>
      </header>

      <div className="grid flex-1 gap-6 lg:grid-cols-[minmax(0,1fr)_24rem]">
        <main className="space-y-5">
          <div className="flex items-baseline justify-between">
            <h2 className="text-lg font-semibold">อุปกรณ์ในบ้าน</h2>
            <p className="text-sm text-slate-500">
              {devices.length} เครื่อง · เปิดอยู่ {onCount}
            </p>
          </div>

          {shownError && <p className="rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-950/50 dark:text-red-300">{shownError}</p>}
          {syncNote && (
            <p role="status" className="flex items-start justify-between gap-3 rounded-lg bg-sky-50 p-3 text-sm text-sky-900 dark:bg-sky-950/50 dark:text-sky-200">
              {syncNote}
              <button onClick={() => setSyncNote(null)} aria-label="ปิด" className="text-sky-700 dark:text-sky-300">
                ✕
              </button>
            </p>
          )}

          {devices.length === 0 && !shownError ? (
            <div className="rounded-2xl border border-dashed border-slate-300 p-8 text-center text-slate-500 dark:border-slate-700">
              ยังไม่มีอุปกรณ์ในระบบ กด "อัปเดตอุปกรณ์" ด้านบน
            </div>
          ) : (
            <div className="space-y-6">
              {groups
                .filter(([, list]) => list.length > 0)
                .map(([room, list]) => (
                  <section key={room ?? '-'} className="space-y-3">
                    {rooms.length > 0 && <h3 className="text-sm font-medium text-slate-500">{room ?? 'ยังไม่ระบุห้อง'}</h3>}
                    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                      {list.map((d) => (
                        <DeviceCard key={d.id} device={d} canControl={canControl} rooms={rooms} onUpdate={upsert} />
                      ))}
                    </div>
                  </section>
                ))}
            </div>
          )}

          <Scenes canControl={canControl} />
          <Documents refreshKey={documentsVersion} />
        </main>

        <aside className="lg:sticky lg:top-5 lg:h-[calc(100vh-7rem)]">
          <ChatPanel onDocuments={() => setDocumentsVersion((v) => v + 1)} />
        </aside>
      </div>
    </div>
  )
}
