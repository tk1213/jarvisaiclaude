import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { api, type PageId, type PageLevel, type Permissions, type User } from '../api'

/** The pages an admin can open to a member, in tab order. Chat has no view-only mode. */
const PAGES: { id: PageId; label: string; viewOnly: boolean }[] = [
  { id: 'home', label: '🏠 บ้าน', viewOnly: true },
  { id: 'flowaccount', label: '📄 FlowAccount', viewOnly: true },
  { id: 'account', label: '💰 Account', viewOnly: true },
  { id: 'personal', label: '💳 การเงินส่วนตัว', viewOnly: true },
  { id: 'chat', label: '💬 แชทกับจาร์วิส', viewOnly: false },
]
const NONE: Permissions = { home: 'none', flowaccount: 'none', account: 'none', personal: 'none', chat: 'none' }

const field =
  'w-full rounded-lg border border-slate-300 bg-transparent px-2.5 py-1.5 outline-none focus:border-sky-500 focus:ring-2 focus:ring-sky-500/30 dark:border-slate-700'
const card = 'space-y-3 rounded-2xl border border-slate-200 bg-white p-4 text-sm dark:border-slate-800 dark:bg-slate-900'
const primary = 'rounded-lg bg-sky-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-sky-700 disabled:opacity-50'
const secondary = 'rounded-lg border border-slate-300 px-3 py-1.5 text-sm hover:border-sky-500 disabled:opacity-50 dark:border-slate-700'

/** Ticks for every page: "ดู" (view) and "แก้ไข" (edit, which includes view); chat is one tick. */
function PageTicks({ value, onChange }: { value: Permissions; onChange: (next: Permissions) => void }) {
  const set = (page: PageId, level: PageLevel) => onChange({ ...value, [page]: level })
  return (
    <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
      {PAGES.map((p) => {
        const level = value[p.id]
        return (
          <div key={p.id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-slate-50 px-3 py-2 dark:bg-slate-800/50">
            <span className="font-medium">{p.label}</span>
            <span className="flex gap-3">
              {p.viewOnly ? (
                <>
                  <label className="flex items-center gap-1.5">
                    <input type="checkbox" checked={level !== 'none'} onChange={(e) => set(p.id, e.target.checked ? 'view' : 'none')} className="size-4 accent-sky-600" />
                    ดู
                  </label>
                  <label className="flex items-center gap-1.5">
                    <input type="checkbox" checked={level === 'edit'} onChange={(e) => set(p.id, e.target.checked ? 'edit' : level === 'none' ? 'none' : 'view')} className="size-4 accent-sky-600" />
                    แก้ไข
                  </label>
                </>
              ) : (
                <label className="flex items-center gap-1.5">
                  <input type="checkbox" checked={level === 'edit'} onChange={(e) => set(p.id, e.target.checked ? 'edit' : 'none')} className="size-4 accent-sky-600" />
                  ใช้งาน
                </label>
              )}
            </span>
          </div>
        )
      })}
    </div>
  )
}

function summary(perms: Permissions): string {
  const open = PAGES.filter((p) => perms[p.id] !== 'none').map((p) => `${p.label}${p.viewOnly ? (perms[p.id] === 'edit' ? ' (แก้ไข)' : ' (ดู)') : ''}`)
  return open.length ? open.join(' · ') : 'ยังไม่ได้เปิดหน้าไหน'
}

function NewMember({ onAdded }: { onAdded: () => void }) {
  const [open, setOpen] = useState(false)
  const [username, setUsername] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [password, setPassword] = useState('')
  const [perms, setPerms] = useState<Permissions>(NONE)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function save(e: FormEvent) {
    e.preventDefault()
    setSaving(true)
    setError(null)
    try {
      await api.addUser({ username: username.trim(), password, display_name: displayName.trim(), permissions: perms })
      setUsername('')
      setDisplayName('')
      setPassword('')
      setPerms(NONE)
      setOpen(false)
      onAdded()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setSaving(false)
    }
  }

  if (!open)
    return (
      <button onClick={() => setOpen(true)} className={primary}>
        + เพิ่มสมาชิก
      </button>
    )
  return (
    <form onSubmit={save} className={card}>
      <h3 className="font-semibold">เพิ่มสมาชิก</h3>
      <div className="grid gap-3 sm:grid-cols-3">
        <label className="space-y-1">
          <span className="text-xs text-slate-500">ชื่อผู้ใช้ (ใช้ล็อกอิน)</span>
          <input value={username} onChange={(e) => setUsername(e.target.value)} required minLength={3} maxLength={64} autoComplete="off" className={field} />
        </label>
        <label className="space-y-1">
          <span className="text-xs text-slate-500">ชื่อที่แสดง</span>
          <input value={displayName} onChange={(e) => setDisplayName(e.target.value)} maxLength={128} className={field} />
        </label>
        <label className="space-y-1">
          <span className="text-xs text-slate-500">รหัสผ่าน (อย่างน้อย 8 ตัว)</span>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={8} autoComplete="new-password" className={field} />
        </label>
      </div>
      <p className="text-xs text-slate-500">เลือกหน้าที่สมาชิกเข้าได้ (ไม่ติ๊ก = มองไม่เห็นหน้านั้น)</p>
      <PageTicks value={perms} onChange={setPerms} />
      {error && <p className="text-red-600 dark:text-red-400">{error}</p>}
      <div className="flex gap-2">
        <button type="submit" disabled={saving} className={primary}>
          {saving ? 'กำลังบันทึก…' : 'บันทึก'}
        </button>
        <button type="button" onClick={() => setOpen(false)} className={secondary}>
          ยกเลิก
        </button>
      </div>
    </form>
  )
}

function MemberCard({ member, onChanged }: { member: User; onChanged: () => void }) {
  const [perms, setPerms] = useState<Permissions>(member.permissions)
  const [displayName, setDisplayName] = useState(member.display_name)
  const [password, setPassword] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const dirty = displayName !== member.display_name || PAGES.some((p) => perms[p.id] !== member.permissions[p.id])

  async function run(action: () => Promise<unknown>, done: string) {
    setBusy(true)
    setError(null)
    setNote(null)
    try {
      await action()
      setNote(done)
      onChanged()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const title = (
    <div className="flex flex-wrap items-baseline gap-2">
      <span className="font-semibold">{member.display_name}</span>
      <span className="text-xs text-slate-500">@{member.username}</span>
      {member.is_admin && <span className="rounded-full bg-sky-100 px-2 py-0.5 text-xs text-sky-800 dark:bg-sky-900/50 dark:text-sky-200">admin</span>}
      {member.line_linked && <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs text-emerald-800 dark:bg-emerald-900/50 dark:text-emerald-200">เชื่อม LINE แล้ว</span>}
    </div>
  )

  if (member.is_admin)
    return (
      <div className={card}>
        {title}
        <p className="text-slate-500">admin เข้าได้ทุกหน้าและแก้ไขได้ทั้งหมดเสมอ</p>
      </div>
    )

  return (
    <div className={card}>
      {title}
      <p className="text-xs text-slate-500">ตอนนี้: {summary(member.permissions)}</p>
      <label className="block max-w-sm space-y-1">
        <span className="text-xs text-slate-500">ชื่อที่แสดง</span>
        <input value={displayName} onChange={(e) => setDisplayName(e.target.value)} maxLength={128} className={field} />
      </label>
      <PageTicks value={perms} onChange={setPerms} />
      {password !== null && (
        <form
          onSubmit={(e) => {
            e.preventDefault()
            void run(() => api.resetPassword(member.id, password), 'ตั้งรหัสผ่านใหม่แล้ว').then(() => setPassword(null))
          }}
          className="flex flex-wrap items-end gap-2"
        >
          <label className="space-y-1">
            <span className="text-xs text-slate-500">รหัสผ่านใหม่ (อย่างน้อย 8 ตัว)</span>
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={8} autoComplete="new-password" className={field} />
          </label>
          <button type="submit" disabled={busy} className={primary}>
            ตั้งรหัสผ่าน
          </button>
          <button type="button" onClick={() => setPassword(null)} className={secondary}>
            ยกเลิก
          </button>
        </form>
      )}
      {error && <p className="text-red-600 dark:text-red-400">{error}</p>}
      {note && <p className="text-emerald-700 dark:text-emerald-300">{note}</p>}
      <div className="flex flex-wrap gap-2">
        <button
          onClick={() => void run(() => api.updateUser(member.id, { display_name: displayName, permissions: perms }), 'บันทึกแล้ว มีผลทันที')}
          disabled={busy || !dirty}
          className={primary}
        >
          บันทึกสิทธิ์
        </button>
        {password === null && (
          <button onClick={() => setPassword('')} disabled={busy} className={secondary}>
            รีเซ็ตรหัสผ่าน
          </button>
        )}
        <button
          onClick={() => {
            if (window.confirm(`ลบสมาชิก ${member.display_name} (@${member.username}) ?\nจะล็อกอินและใช้ LINE ไม่ได้อีก และประวัติแชทจะถูกลบ`)) void run(() => api.deleteUser(member.id), 'ลบแล้ว')
          }}
          disabled={busy}
          className="rounded-lg px-3 py-1.5 text-sm text-red-600 hover:bg-red-50 disabled:opacity-50 dark:text-red-400 dark:hover:bg-red-950/50"
        >
          ลบสมาชิก
        </button>
      </div>
    </div>
  )
}

/** 👥 สมาชิก (admin only): add members, tick which pages each may open (view / edit), reset passwords, remove. */
export function Members() {
  const [members, setMembers] = useState<User[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    api.users().then(setMembers, (e) => setError((e as Error).message))
  }, [])
  useEffect(load, [load])

  return (
    <main className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">สมาชิกและสิทธิ์การเข้าหน้า</h2>
          <p className="text-sm text-slate-500">ติ๊ก "ดู" = เปิดหน้านั้นได้แต่แก้ไม่ได้, "แก้ไข" = เพิ่ม/แก้/ลบได้ด้วย สิทธิ์นี้ใช้กับแชทจาร์วิสและ LINE ด้วย</p>
        </div>
        <NewMember onAdded={load} />
      </div>
      {error && <p className="rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-950/50 dark:text-red-300">{error}</p>}
      {members === null && !error && <p className="text-sm text-slate-500">กำลังโหลด…</p>}
      <div className="space-y-3">
        {members?.map((m) => (
          <MemberCard key={m.id} member={m} onChanged={load} />
        ))}
      </div>
    </main>
  )
}
