import { useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { api, fetchBlob, type BankAccount, type PersonalEntry, type PersonalKind } from '../api'
import { baht, defaultDate, thaiDate, thisMonth } from '../months'

const field =
  'w-full rounded-lg border border-slate-300 bg-transparent px-2.5 py-1.5 outline-none focus:border-sky-500 focus:ring-2 focus:ring-sky-500/30 dark:border-slate-700'
const caption = 'text-xs text-slate-500'

function useEscape(onClose: () => void) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
}

function Dialog({ title, onClose, onSubmit, children, error, saving }: { title: string; onClose: () => void; onSubmit: (e: FormEvent) => void; children: ReactNode; error: string | null; saving: boolean }) {
  useEscape(onClose)
  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-slate-900/50 p-4 sm:items-center"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <form onSubmit={onSubmit} role="dialog" aria-modal="true" className="w-full max-w-lg space-y-4 rounded-2xl bg-white p-5 text-sm shadow-xl dark:bg-slate-900">
        <h3 className="text-base font-semibold">{title}</h3>
        {children}
        {error && (
          <p role="alert" className="text-xs text-red-700 dark:text-red-300">
            {error}
          </p>
        )}
        <div className="flex justify-end gap-2">
          <button type="button" onClick={onClose} className="rounded-lg border border-slate-300 px-4 py-2 hover:border-slate-400 dark:border-slate-700">
            ยกเลิก
          </button>
          <button disabled={saving} className="rounded-lg bg-sky-600 px-4 py-2 font-medium text-white hover:bg-sky-700 disabled:opacity-50">
            {saving ? 'กำลังบันทึก…' : 'บันทึก'}
          </button>
        </div>
      </form>
    </div>
  )
}

/** Add or edit one income, expense or transfer between the owner's own accounts. */
export function PersonalEntryForm({
  kind: pageKind,
  entry,
  month,
  accounts,
  onSaved,
  onClose,
}: {
  kind: 'income' | 'expense'
  entry: PersonalEntry | null
  month: string
  accounts: BankAccount[]
  onSaved: () => void
  onClose: () => void
}) {
  const fallback = accounts.find((a) => a.is_default) ?? accounts[0]
  const [kind, setKind] = useState<PersonalKind>(entry?.kind ?? pageKind)
  const [accountId, setAccountId] = useState(entry?.account_id ?? fallback?.id ?? 0)
  const [toAccountId, setToAccountId] = useState(entry?.to_account_id ?? accounts.find((a) => a.id !== (entry?.account_id ?? fallback?.id))?.id ?? 0)
  const [date, setDate] = useState(() => entry?.date ?? defaultDate(month))
  const [time, setTime] = useState(entry?.time ?? '')
  const [amount, setAmount] = useState(entry ? String(entry.amount) : '')
  const [counterparty, setCounterparty] = useState(entry?.counterparty ?? '')
  const [note, setNote] = useState(entry?.note ?? '')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function save(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setSaving(true)
    try {
      const body = { kind, date, time, amount: Number(amount), account_id: accountId, to_account_id: kind === 'transfer' ? toAccountId : null, counterparty, note }
      if (entry) await api.editPersonalEntry(entry.id, body)
      else await api.addPersonalEntry(body)
      onSaved()
    } catch (err) {
      setError((err as Error).message)
      setSaving(false)
    }
  }

  const transfer = kind === 'transfer'
  const options = accounts.map((a) => (
    <option key={a.id} value={a.id}>
      {a.label}
    </option>
  ))
  return (
    <Dialog title={`${entry ? 'แก้ไข' : 'เพิ่ม'}รายการ`} onClose={onClose} onSubmit={(e) => void save(e)} error={error} saving={saving}>
      <div className="grid grid-cols-3 gap-1 rounded-xl bg-slate-100 p-1 dark:bg-slate-800/60">
        {(
          [
            ['income', 'รายรับ'],
            ['expense', 'รายจ่าย'],
            ['transfer', 'โอนระหว่างบัญชี'],
          ] as const
        ).map(([k, label]) => (
          <button
            key={k}
            type="button"
            onClick={() => setKind(k)}
            aria-pressed={kind === k}
            className={`rounded-lg px-2 py-1.5 text-xs font-medium ${kind === k ? 'bg-white text-sky-700 shadow-sm dark:bg-slate-900 dark:text-sky-300' : 'text-slate-500'}`}
          >
            {label}
          </button>
        ))}
      </div>
      <div className={`grid gap-3 ${transfer ? 'sm:grid-cols-2' : ''}`}>
        <label className="space-y-1">
          <span className={caption}>{transfer ? 'จากบัญชี' : kind === 'income' ? 'เข้าบัญชี' : 'จ่ายจากบัญชี'}</span>
          <select value={accountId} onChange={(e) => setAccountId(Number(e.target.value))} required className={field}>
            {options}
          </select>
        </label>
        {transfer && (
          <label className="space-y-1">
            <span className={caption}>ไปบัญชี</span>
            <select value={toAccountId} onChange={(e) => setToAccountId(Number(e.target.value))} required className={field}>
              {options}
            </select>
          </label>
        )}
      </div>
      <div className="grid grid-cols-[1fr_7rem_9rem] gap-3">
        <label className="space-y-1">
          <span className={caption}>วันที่</span>
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)} required className={field} />
        </label>
        <label className="space-y-1">
          <span className={caption}>เวลา</span>
          <input type="time" value={time} onChange={(e) => setTime(e.target.value)} className={field} />
        </label>
        <label className="space-y-1">
          <span className={caption}>จำนวนเงิน (บาท)</span>
          <input value={amount} onChange={(e) => setAmount(e.target.value)} type="number" min="0.01" step="0.01" required className={field} />
        </label>
      </div>
      {!transfer && (
        <label className="block space-y-1">
          <span className={caption}>{kind === 'income' ? 'ผู้โอนให้' : 'จ่ายให้'}</span>
          <input value={counterparty} onChange={(e) => setCounterparty(e.target.value)} maxLength={256} className={field} />
        </label>
      )}
      <label className="block space-y-1">
        <span className={caption}>รายละเอียด</span>
        <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={2000} className={field} />
      </label>
    </Dialog>
  )
}

/** Add or edit a bank or fund account: bank (or กองทุน A–F), nickname, number, opening balance and its date, default for typed LINE entries. */
export function PersonalAccountForm({ account, onSaved, onClose }: { account: BankAccount | null; onSaved: () => void; onClose: () => void }) {
  const [banks, setBanks] = useState<{ code: string; name: string }[]>([])
  const [bank, setBank] = useState(account?.bank ?? 'KBANK')
  const [nickname, setNickname] = useState(account?.nickname ?? '')
  const [accountNo, setAccountNo] = useState(account?.account_no ?? '')
  const [opening, setOpening] = useState(account ? String(account.opening) : '0')
  const [openingDate, setOpeningDate] = useState(() => account?.opening_date ?? defaultDate(thisMonth()))
  const [isDefault, setIsDefault] = useState(account?.is_default ?? false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const fund = bank.startsWith('FUND_')

  useEffect(() => {
    api.banks().then(setBanks, (e) => setError((e as Error).message))
  }, [])

  async function save(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setSaving(true)
    try {
      const body = { bank, nickname, account_no: accountNo, opening: Number(opening) || 0, opening_date: openingDate, is_default: isDefault }
      if (account) await api.editBankAccount(account.id, body)
      else await api.addBankAccount(body)
      onSaved()
    } catch (err) {
      setError((err as Error).message)
      setSaving(false)
    }
  }

  return (
    <Dialog title={account ? 'แก้ไขบัญชี' : 'เพิ่มบัญชี / กองทุน'} onClose={onClose} onSubmit={(e) => void save(e)} error={error} saving={saving}>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="space-y-1">
          <span className={caption}>ธนาคาร / กองทุน</span>
          <select value={bank} onChange={(e) => setBank(e.target.value)} className={field}>
            {banks.map((b) => (
              <option key={b.code} value={b.code}>
                {b.name}
              </option>
            ))}
          </select>
        </label>
        <label className="space-y-1">
          <span className={caption}>{fund ? 'ชื่อกองทุน' : 'ชื่อเรียก (ไม่ใส่ก็ได้)'}</span>
          <input value={nickname} onChange={(e) => setNickname(e.target.value)} placeholder={fund ? 'เช่น K-SET50' : 'เช่น กสิกร ใช้จ่าย'} maxLength={64} className={field} />
        </label>
      </div>
      <label className="block space-y-1">
        <span className={caption}>{fund ? 'เลขบัญชีกองทุน (ไม่ใส่ก็ได้)' : 'เลขบัญชี (เต็ม หรือ 4 ตัวท้าย)'}</span>
        <input value={accountNo} onChange={(e) => setAccountNo(e.target.value)} inputMode="numeric" placeholder="123-4-56789-0" maxLength={32} className={field} />
      </label>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="space-y-1">
          <span className={caption}>เงินต้น (ยอดในบัญชี ณ วันที่)</span>
          <input value={opening} onChange={(e) => setOpening(e.target.value)} type="number" step="0.01" className={field} />
        </label>
        <label className="space-y-1">
          <span className={caption}>ณ วันที่</span>
          <input type="date" value={openingDate} onChange={(e) => setOpeningDate(e.target.value)} required className={field} />
        </label>
      </div>
      <p className="text-xs text-slate-500">นับรายการตั้งแต่วันที่นี้เป็นต้นไป (รายการก่อนหน้านี้ไม่นำมาคิดยอด)</p>
      <label className="flex items-center gap-2">
        <input type="checkbox" checked={isDefault} onChange={(e) => setIsDefault(e.target.checked)} />
        บัญชีหลัก (ใช้เมื่อพิมพ์ใน LINE โดยไม่บอกธนาคาร)
      </label>
    </Dialog>
  )
}

/** The slip picture kept from LINE, fetched with the login token. */
export function SlipViewer({ entry, onClose }: { entry: PersonalEntry; onClose: () => void }) {
  const [url, setUrl] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEscape(onClose)

  useEffect(() => {
    let objectUrl: string | null = null
    fetchBlob(`/personal/entries/${entry.id}/slip`).then(
      (blob) => {
        objectUrl = URL.createObjectURL(blob)
        setUrl(objectUrl)
      },
      (e) => setError((e as Error).message),
    )
    return () => {
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [entry.id])

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/70 p-4" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div role="dialog" aria-modal="true" className="max-h-full space-y-2 overflow-y-auto rounded-2xl bg-white p-3 text-sm shadow-xl dark:bg-slate-900">
        <div className="flex items-center justify-between gap-4">
          <p className="font-medium">
            สลิป {baht.format(entry.amount)} บาท · {thaiDate(entry.date)} {entry.time}
          </p>
          <button onClick={onClose} aria-label="ปิด" className="rounded px-2 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800">
            ✕
          </button>
        </div>
        {error && <p className="text-red-700 dark:text-red-300">{error}</p>}
        {url ? <img src={url} alt="สลิป" className="max-h-[80vh] w-auto rounded-lg" /> : !error && <p className="p-8 text-slate-500">กำลังโหลด…</p>}
      </div>
    </div>
  )
}
