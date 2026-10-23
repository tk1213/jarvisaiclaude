import { useEffect, useState } from 'react'
import { api, can, getToken, setToken, type User } from './api'
import { Account } from './components/Account'
import { Catalog } from './components/Catalog'
import { ChatPanel } from './components/ChatPanel'
import { DeviceCard } from './components/DeviceCard'
import { Documents } from './components/Documents'
import { LineLink } from './components/LineLink'
import { Login } from './components/Login'
import { Members } from './components/Members'
import { PageNamesEditor } from './components/PageNamesEditor'
import { Personal } from './components/Personal'
import { Scenes } from './components/Scenes'
import { powerCode } from './readings'
import { DEFAULT_NAMES, PageNamesContext, type PageKey, type PageNames } from './pageNames'
import { useDevices, type LinkState } from './useDevices'

type Page = PageKey
/** Tab order; the names come from the server (an admin can change them). */
const PAGES: { id: Page }[] = [{ id: 'home' }, { id: 'flowaccount' }, { id: 'account' }, { id: 'personal' }, { id: 'company' }, { id: 'members' }]

/** Whether this user may open a page: the members page is for admins, the rest follow the ticks an admin set. */
function mayOpen(user: User | null, page: Page): boolean {
  if (!user) return false
  return page === 'members' ? user.is_admin : can(user, page)
}

/** The page from the address (#flowaccount, #account, #personal, #company, #members), so a refresh or bookmark lands on the same page. */
function pageFromHash(): Page {
  const page = location.hash.slice(1)
  return PAGES.find((p) => p.id === page)?.id ?? 'home'
}

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
  const [user, setUser] = useState<User | null>(null)
  const { devices, link, error, upsert, setDevices } = useDevices(user ? can(user, 'home') : null)
  const [syncing, setSyncing] = useState(false)
  const [syncError, setSyncError] = useState<string | null>(null)
  const [syncNote, setSyncNote] = useState<string | null>(null)
  const [documentsVersion, setDocumentsVersion] = useState(0)
  const [page, setPage] = useState<Page>(pageFromHash)
  const [names, setNames] = useState<PageNames>(DEFAULT_NAMES)
  const [renaming, setRenaming] = useState(false)

  useEffect(() => {
    const onHash = () => setPage(pageFromHash())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  function go(next: Page) {
    history.replaceState(null, '', next === 'home' ? location.pathname : `#${next}`)
    setPage(next)
  }

  useEffect(() => {
    api.pageNames().then(setNames, () => {})
  }, [])

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

  const canControl = can(user, 'home', 'edit')
  const allowedPages = PAGES.filter((p) => mayOpen(user, p.id))
  // A page this member can't open (e.g. from an old bookmark) shows their first allowed page instead.
  const shown: Page | null = user ? (mayOpen(user, page) ? page : (allowedPages[0]?.id ?? null)) : null
  const chat = can(user, 'chat')
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
    <PageNamesContext.Provider value={names}>
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
          {(chat || can(user, 'personal', 'edit')) && <LineLink />}
          {shown === 'home' && canControl && (
            <button
              onClick={() => void sync()}
              disabled={syncing}
              className="rounded-lg border border-slate-300 px-3 py-1.5 hover:border-sky-500 disabled:opacity-50 dark:border-slate-700"
            >
              {syncing ? 'กำลังอัปเดต…' : 'อัปเดตอุปกรณ์'}
            </button>
          )}
          <button onClick={onLogout} className="rounded-lg px-3 py-1.5 text-slate-500 hover:bg-slate-200 dark:hover:bg-slate-800">
            ออกจากระบบ
          </button>
        </div>
      </header>

      <nav className="-mt-2 flex gap-1 overflow-x-auto [scrollbar-width:none] border-b border-slate-200 dark:border-slate-800">
        {allowedPages.map((p) => (
          <button
            key={p.id}
            onClick={() => go(p.id)}
            aria-current={shown === p.id ? 'page' : undefined}
            className={`-mb-px shrink-0 border-b-2 px-4 py-2 text-sm font-medium whitespace-nowrap ${
              shown === p.id ? 'border-sky-600 text-sky-700 dark:text-sky-300' : 'border-transparent text-slate-500 hover:text-slate-800 dark:hover:text-slate-200'
            }`}
          >
            {names[p.id]}
          </button>
        ))}
        {user?.is_admin && !renaming && (
          <button onClick={() => setRenaming(true)} title="แก้ชื่อหน้า" aria-label="แก้ชื่อหน้า" className="-mb-px shrink-0 px-2 py-2 text-sm text-slate-400 hover:text-sky-600">
            ✏️
          </button>
        )}
      </nav>
      {renaming && <PageNamesEditor pages={allowedPages.map((p) => p.id)} names={names} onSaved={setNames} onClose={() => setRenaming(false)} />}

      {shown === null ? (
        <p className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-950/50 dark:text-amber-200">
          {user ? `บัญชีนี้ยังไม่ได้รับสิทธิ์เข้าหน้าไหน ติดต่อ admin ให้เปิดสิทธิ์ในหน้า ${names.members}` : 'กำลังโหลด…'}
        </p>
      ) : shown === 'members' ? (
        <Members />
      ) : shown === 'account' ? (
        <Account canEdit={can(user, 'account', 'edit')} />
      ) : shown === 'personal' ? (
        <Personal book="personal" canEdit={can(user, 'personal', 'edit')} canMove={can(user, 'personal', 'edit') && can(user, 'company', 'edit')} />
      ) : shown === 'company' ? (
        <Personal book="company" canEdit={can(user, 'company', 'edit')} />
      ) : (
        <div className={`grid flex-1 gap-6 ${chat ? 'lg:grid-cols-[minmax(0,1fr)_24rem]' : ''}`}>
          {shown === 'flowaccount' ? (
            <main className="space-y-6">
              <h2 className="text-lg font-semibold">เอกสารและสินค้า FlowAccount</h2>
              <Documents refreshKey={documentsVersion} />
              <Catalog refreshKey={documentsVersion} canEdit={can(user, 'flowaccount', 'edit')} />
            </main>
          ) : (
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
            </main>
          )}

          {chat && (
            <aside className="lg:sticky lg:top-5 lg:h-[calc(100vh-7rem)]">
              <ChatPanel page={shown} onDocuments={() => setDocumentsVersion((v) => v + 1)} />
            </aside>
          )}
        </div>
      )}
    </div>
    </PageNamesContext.Provider>
  )
}
