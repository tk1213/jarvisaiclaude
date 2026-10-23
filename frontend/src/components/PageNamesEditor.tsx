import { useState } from 'react'
import { api } from '../api'
import { DEFAULT_NAMES, type PageKey, type PageNames } from '../pageNames'

/** The tabs as text boxes, for an admin to rename pages. Saved names reach every screen and member. */
export function PageNamesEditor({ pages, names, onSaved, onClose }: { pages: PageKey[]; names: PageNames; onSaved: (names: PageNames) => void; onClose: () => void }) {
  const [draft, setDraft] = useState<PageNames>(names)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function save(next: PageNames) {
    setSaving(true)
    setError(null)
    try {
      onSaved(await api.savePageNames(next))
      onClose()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="-mt-2 space-y-2 rounded-xl border border-sky-200 bg-sky-50 p-3 text-sm dark:border-sky-900 dark:bg-sky-950/40">
      <p className="text-xs text-slate-600 dark:text-slate-300">แก้ชื่อแต่ละหน้า (ใส่อีโมจิได้ ยาวไม่เกิน 40 ตัว เว้นว่าง = ชื่อเดิม) ทุกคนจะเห็นชื่อใหม่ รวมถึงข้อความที่จาร์วิสตอบใน LINE</p>
      <div className="flex flex-wrap gap-2">
        {pages.map((id) => (
          <input
            key={id}
            value={draft[id]}
            onChange={(e) => setDraft({ ...draft, [id]: e.target.value })}
            maxLength={40}
            placeholder={DEFAULT_NAMES[id]}
            aria-label={`ชื่อหน้า ${DEFAULT_NAMES[id]}`}
            className="w-44 rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 outline-none focus:border-sky-500 focus:ring-2 focus:ring-sky-500/30 dark:border-slate-700 dark:bg-slate-900"
          />
        ))}
      </div>
      {error && <p className="text-red-600 dark:text-red-400">{error}</p>}
      <div className="flex flex-wrap gap-2">
        <button onClick={() => void save(draft)} disabled={saving} className="rounded-lg bg-sky-600 px-3 py-1.5 font-medium text-white hover:bg-sky-700 disabled:opacity-50">
          {saving ? 'กำลังบันทึก…' : 'บันทึกชื่อ'}
        </button>
        <button onClick={onClose} disabled={saving} className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 hover:border-sky-500 dark:border-slate-700 dark:bg-slate-900">
          ยกเลิก
        </button>
        <button
          onClick={() => {
            if (window.confirm('คืนชื่อเดิมของทุกหน้า ?')) void save(DEFAULT_NAMES)
          }}
          disabled={saving}
          className="rounded-lg px-3 py-1.5 text-slate-600 hover:bg-white dark:text-slate-300 dark:hover:bg-slate-900"
        >
          คืนชื่อเดิม
        </button>
      </div>
    </div>
  )
}
