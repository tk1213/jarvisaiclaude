import { useCallback, useEffect, useState } from 'react'
import { api, type BankAccount, type Book, type PersonalEntry, type PersonalSummary } from '../api'
import { BookContext, useBook } from '../book'
import { usePageNames } from '../pageNames'
import { baht, thaiDate, thaiMonth, thisMonth } from '../months'
import { MonthPicker } from './MonthPicker'
import { PersonalAccountForm, PersonalEntryForm, SlipViewer } from './PersonalForms'

type Tab = 'balance' | 'income' | 'expense' | 'accounts'
const TABS: { id: Tab; label: string }[] = [
  { id: 'balance', label: 'ยอดคงเหลือ' },
  { id: 'income', label: 'รายรับ' },
  { id: 'expense', label: 'รายจ่าย' },
  { id: 'accounts', label: 'บัญชี / กองทุน' },
]

const SOURCE: Record<PersonalEntry['source'], string> = { slip: 'สลิป LINE', text: 'พิมพ์ใน LINE', manual: 'เพิ่มเอง' }
/** Where LINE entries for each book come from. */
const GROUPS: Record<Book, string> = { personal: '"TKรับจ่าย"', company: '"สลิปรายรับ" / "สลิปรายจ่าย"' }

/** 💳 Personal money (LINE group "TKรับจ่าย") or 🏢 company money ("สลิปรายรับ" / "สลิปรายจ่าย"): balances per bank or
 * fund account, income and expenses, and the accounts. canEdit false = view only. canMove: personal entries can be
 * ticked and moved to company money (for entries the slip groups recorded here before the company page existed). */
export function Personal({ book, canEdit, canMove = false }: { book: Book; canEdit: boolean; canMove?: boolean }) {
  return (
    <BookContext.Provider value={book}>
      <MoneyPage key={book} canEdit={canEdit} canMove={canMove} />
    </BookContext.Provider>
  )
}

function MoneyPage({ canEdit, canMove }: { canEdit: boolean; canMove: boolean }) {
  const book = useBook()
  const names = usePageNames()
  const [tab, setTab] = useState<Tab>('balance')
  const [month, setMonth] = useState(thisMonth)
  const [accounts, setAccounts] = useState<BankAccount[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [version, setVersion] = useState(0)

  useEffect(() => {
    api.bankAccounts(book).then(setAccounts, (e) => setError((e as Error).message))
  }, [book, version])

  const changed = () => setVersion((v) => v + 1)

  return (
    <main className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">{names[book]}</h2>
          <p className="text-xs text-slate-500">รายการจาก LINE มาจากกลุ่ม {GROUPS[book]}</p>
        </div>
        {tab !== 'accounts' && <MonthPicker month={month} onChange={setMonth} />}
      </div>
      {error && <p className="rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-950/50 dark:text-red-300">{error}</p>}

      <nav className="flex gap-1 rounded-xl bg-slate-100 p-1 text-sm dark:bg-slate-800/60">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            aria-current={tab === t.id ? 'page' : undefined}
            className={`flex-1 rounded-lg px-3 py-1.5 font-medium ${tab === t.id ? 'bg-white text-sky-700 shadow-sm dark:bg-slate-900 dark:text-sky-300' : 'text-slate-500 hover:text-slate-800 dark:hover:text-slate-200'}`}
          >
            {t.label}
          </button>
        ))}
      </nav>

      {accounts && accounts.length === 0 && tab !== 'accounts' ? (
        <div className="rounded-2xl border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500 dark:border-slate-700">
          ยังไม่มีบัญชีธนาคาร
          {canEdit && (
            <>
              {' '}
              <button onClick={() => setTab('accounts')} className="text-sky-700 underline dark:text-sky-300">
                เพิ่มบัญชีธนาคาร
              </button>{' '}
              พร้อมเงินต้นก่อน แล้วค่อยส่งสลิปในกลุ่ม LINE {GROUPS[book]}
            </>
          )}
        </div>
      ) : tab === 'balance' ? (
        <Balances month={month} version={version} />
      ) : tab === 'accounts' ? (
        <Accounts accounts={accounts} canEdit={canEdit} onChange={changed} />
      ) : (
        <Entries key={tab} kind={tab} month={month} accounts={accounts ?? []} version={version} canEdit={canEdit} canMove={canMove && book === 'personal'} onChange={changed} />
      )}
    </main>
  )
}

function Balances({ month, version }: { month: string; version: number }) {
  const book = useBook()
  const [data, setData] = useState<PersonalSummary | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.personalSummary(book, month).then(setData, (e) => setError((e as Error).message))
  }, [book, month, version])

  if (error) return <p className="rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-950/50 dark:text-red-300">{error}</p>
  if (!data) return <p className="text-sm text-slate-500">กำลังโหลด…</p>
  return (
    <section className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-3">
        <Stat label="ยอดคงเหลือรวม (วันนี้)" value={data.total} strong />
        <Stat label={`รายรับ ${thaiMonth(month)}`} value={data.month_in} tone="text-emerald-700 dark:text-emerald-400" />
        <Stat label={`รายจ่าย ${thaiMonth(month)}`} value={data.month_out} tone="text-rose-700 dark:text-rose-400" />
      </div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {data.accounts.map((a) => (
          <div key={a.id} className="space-y-2 rounded-2xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
            <div className="flex items-baseline justify-between gap-2">
              <p className="font-medium">{a.label}</p>
              <p className="text-xs text-slate-500">{a.bank_name}</p>
            </div>
            <p className={`text-2xl font-semibold tabular-nums ${a.balance < 0 ? 'text-rose-700 dark:text-rose-400' : ''}`}>{baht.format(a.balance)}</p>
            <p className="flex justify-between text-xs text-slate-500 tabular-nums">
              <span>เดือนนี้ รับ {baht.format(a.month_in)}</span>
              <span>จ่าย {baht.format(a.month_out)}</span>
            </p>
          </div>
        ))}
      </div>
      <p className="text-xs text-slate-500">
        ยอดคงเหลือ = เงินต้น + รายรับ − รายจ่าย ± โอนระหว่างบัญชี ตั้งแต่วันที่ของเงินต้น (ไม่ขึ้นกับเดือนที่เลือก) · รับ/จ่ายของแต่ละบัญชีรวมเงินโอนเข้า/ออก
        แต่ยอดรายรับ/รายจ่ายรวมของเดือนไม่นับการโอนระหว่างบัญชี · กองทุนแสดงเป็นเงินต้นที่โอนเข้าไป
      </p>
    </section>
  )
}

function Stat({ label, value, tone = '', strong = false }: { label: string; value: number; tone?: string; strong?: boolean }) {
  return (
    <div className={`rounded-2xl p-4 ${strong ? 'bg-sky-600 text-white' : 'border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900'}`}>
      <p className={`text-xs ${strong ? 'text-sky-100' : 'text-slate-500'}`}>{label}</p>
      <p className={`text-2xl font-semibold tabular-nums ${tone}`}>{baht.format(value)}</p>
    </div>
  )
}

function Entries({
  kind,
  month,
  accounts,
  version,
  canEdit,
  canMove,
  onChange,
}: {
  kind: 'income' | 'expense'
  month: string
  accounts: BankAccount[]
  version: number
  canEdit: boolean
  canMove: boolean
  onChange: () => void
}) {
  const book = useBook()
  const [accountId, setAccountId] = useState(0)
  const [rows, setRows] = useState<PersonalEntry[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [editing, setEditing] = useState<PersonalEntry | 'new' | null>(null)
  const [slip, setSlip] = useState<PersonalEntry | null>(null)

  const load = useCallback(() => {
    api.personalEntries(book, kind, month, accountId || undefined).then(setRows, (e) => setError((e as Error).message))
  }, [book, kind, month, accountId])
  useEffect(load, [load, version])

  async function remove(e: PersonalEntry) {
    if (!window.confirm(`ลบรายการ ${baht.format(e.amount)} บาท วันที่ ${thaiDate(e.date)} ?${e.has_slip ? ' (รูปสลิปจะถูกลบด้วย)' : ''}`)) return
    try {
      await api.deletePersonalEntry(book, e.id)
      onChange()
    } catch (err) {
      setError((err as Error).message)
    }
  }

  const [picked, setPicked] = useState<Set<number>>(new Set())
  const toggle = (id: number, on: boolean) =>
    setPicked((prev) => {
      const next = new Set(prev)
      if (on) next.add(id)
      else next.delete(id)
      return next
    })

  const income = kind === 'income'
  const word = income ? 'รายรับ' : 'รายจ่าย'
  const own = (rows ?? []).filter((r) => r.kind === kind)
  const total = own.reduce((s, r) => s + r.amount, 0)

  return (
    <section className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-sm">
          <select
            value={accountId}
            onChange={(e) => setAccountId(Number(e.target.value))}
            aria-label="บัญชี"
            className="rounded-lg border border-slate-300 bg-transparent px-2 py-1 dark:border-slate-700"
          >
            <option value={0}>ทุกบัญชี</option>
            {accounts.map((a) => (
              <option key={a.id} value={a.id}>
                {a.label}
              </option>
            ))}
          </select>
          <span className="text-slate-500">
            {rows ? `${own.length} รายการ · รวม ` : 'กำลังโหลด…'}
            {rows && <span className={`font-medium tabular-nums ${income ? 'text-emerald-700 dark:text-emerald-400' : 'text-rose-700 dark:text-rose-400'}`}>{baht.format(total)}</span>}
          </span>
        </div>
        {canEdit && (
          <button onClick={() => setEditing('new')} className="rounded-lg bg-sky-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-sky-700">
            + เพิ่ม{word}
          </button>
        )}
      </div>
      {error && <p className="rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-950/50 dark:text-red-300">{error}</p>}
      {canMove && <MoveBar picked={picked} onMoved={() => {
        setPicked(new Set())
        onChange()
      }} />}

      <div className="overflow-x-auto rounded-2xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
        <table className="w-full min-w-[48rem] text-sm">
          <thead className="bg-slate-50 text-xs text-slate-500 dark:bg-slate-800/60">
            <tr>
              {canMove && <th className="w-8 px-3 py-2" aria-label="เลือก" />}
              <th className="px-3 py-2 text-left font-medium">วันที่</th>
              <th className="px-3 py-2 text-left font-medium">บัญชี</th>
              <th className="px-3 py-2 text-left font-medium">{income ? 'ผู้โอนให้' : 'จ่ายให้'}</th>
              <th className="px-3 py-2 text-left font-medium">รายละเอียด</th>
              <th className="px-3 py-2 text-right font-medium">จำนวนเงิน</th>
              <th className="px-3 py-2" />
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
            {rows?.map((r) => {
              const transfer = r.kind === 'transfer'
              // A transfer shows here as money in to its destination (income page) or out of its source (expense page).
              const account = transfer && income ? r.to_account : r.account
              const other = transfer ? (income ? `จาก ${r.account}` : `ไป ${r.to_account}`) : r.counterparty
              return (
                <tr key={r.id} className={transfer ? 'text-slate-500' : ''}>
                  {canMove && (
                    <td className="px-3 py-2">
                      {!transfer && (
                        <input
                          type="checkbox"
                          checked={picked.has(r.id)}
                          onChange={(e) => toggle(r.id, e.target.checked)}
                          aria-label="เลือกเพื่อย้ายไปการเงินบริษัท"
                          className="size-4 accent-sky-600"
                        />
                      )}
                    </td>
                  )}
                  <td className="px-3 py-2 whitespace-nowrap">
                    {thaiDate(r.date)}
                    {r.time && <span className="ml-1 text-xs text-slate-500">{r.time}</span>}
                  </td>
                  <td className="px-3 py-2">
                    {transfer && <span className="mr-1.5 rounded bg-slate-100 px-1.5 text-xs dark:bg-slate-800">{income ? 'รับโอน' : 'โอนออก'}</span>}
                    {account}
                  </td>
                  <td className="px-3 py-2">{other || '-'}</td>
                  <td className="max-w-[16rem] px-3 py-2 text-slate-600 dark:text-slate-300">
                    <span className="line-clamp-1">{r.note}</span>
                    <span className="text-[10px] text-slate-400">
                      {SOURCE[r.source]}
                      {r.ref_no && ` · อ้างอิง ${r.ref_no}`}
                    </span>
                  </td>
                  <td
                    className={`px-3 py-2 text-right font-medium tabular-nums ${transfer ? '' : income ? 'text-emerald-700 dark:text-emerald-400' : 'text-rose-700 dark:text-rose-400'}`}
                  >
                    {baht.format(r.amount)}
                  </td>
                  <td className="px-3 py-2 text-right whitespace-nowrap">
                    {r.has_slip && (
                      <button onClick={() => setSlip(r)} className="rounded px-1.5 py-0.5 text-xs text-sky-700 hover:bg-sky-50 dark:text-sky-300 dark:hover:bg-sky-950/50">
                        🧾 สลิป
                      </button>
                    )}
                    {canEdit && (
                      <>
                        <button onClick={() => setEditing(r)} className="rounded px-1.5 py-0.5 text-xs text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800">
                          แก้ไข
                        </button>
                        <button onClick={() => void remove(r)} className="rounded px-1.5 py-0.5 text-xs text-red-600 hover:bg-red-50 dark:hover:bg-red-950/50">
                          ลบ
                        </button>
                      </>
                    )}
                  </td>
                </tr>
              )
            })}
            {rows?.length === 0 && (
              <tr>
                <td colSpan={canMove ? 7 : 6} className="px-3 py-8 text-center text-slate-500">
                  ยังไม่มี{word}ในเดือนนี้ ส่งสลิปในกลุ่ม LINE {GROUPS[book]} หรือกด "+ เพิ่ม{word}"
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {editing && (
        <PersonalEntryForm
          kind={kind}
          entry={editing === 'new' ? null : editing}
          month={month}
          accounts={accounts}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null)
            onChange()
          }}
        />
      )}
      {slip && <SlipViewer entry={slip} onClose={() => setSlip(null)} />}
    </section>
  )
}

/** Move ticked personal entries to company money, into one of its accounts. */
function MoveBar({ picked, onMoved }: { picked: Set<number>; onMoved: () => void }) {
  const company = usePageNames().company
  const [targets, setTargets] = useState<BankAccount[] | null>(null)
  const [target, setTarget] = useState(0)
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState<string | null>(null)

  useEffect(() => {
    api.bankAccounts('company').then(
      (accs) => {
        setTargets(accs)
        setTarget((t) => t || accs.find((a) => a.is_default)?.id || accs[0]?.id || 0)
      },
      (e) => setNote((e as Error).message),
    )
  }, [])

  async function move() {
    if (!window.confirm(`ย้าย ${picked.size} รายการไปหน้า ${company} ?`)) return
    setBusy(true)
    setNote(null)
    try {
      const r = await api.moveToCompany([...picked], target)
      setNote(`ย้ายไปหน้า ${company} แล้ว ${r.moved} รายการ`)
      onMoved()
    } catch (e) {
      setNote((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-xl bg-sky-50 px-3 py-2 text-sm text-sky-900 dark:bg-sky-950/40 dark:text-sky-100">
      <span>ติ๊กรายการของบริษัท (เช่น ที่เคยมาจากกลุ่มสลิปรายรับ/สลิปรายจ่าย) แล้วย้ายไปหน้า {company}</span>
      {targets && targets.length === 0 ? (
        <span className="text-amber-700 dark:text-amber-300">เพิ่มบัญชีธนาคารในหน้า {company} ก่อน</span>
      ) : (
        <>
          <select
            value={target}
            onChange={(e) => setTarget(Number(e.target.value))}
            aria-label="บัญชีบริษัทปลายทาง"
            className="rounded-lg border border-slate-300 bg-white px-2 py-1 dark:border-slate-700 dark:bg-slate-900"
          >
            {targets?.map((a) => (
              <option key={a.id} value={a.id}>
                {a.label}
              </option>
            ))}
          </select>
          <button onClick={() => void move()} disabled={busy || picked.size === 0 || !target} className="rounded-lg bg-sky-600 px-3 py-1 font-medium text-white hover:bg-sky-700 disabled:opacity-50">
            ย้าย {picked.size} รายการไป {company}
          </button>
        </>
      )}
      {note && <span>{note}</span>}
    </div>
  )
}

function Accounts({ accounts, canEdit, onChange }: { accounts: BankAccount[] | null; canEdit: boolean; onChange: () => void }) {
  const book = useBook()
  const [editing, setEditing] = useState<BankAccount | 'new' | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function remove(a: BankAccount) {
    if (!window.confirm(`ลบบัญชี ${a.label} ?`)) return
    setError(null)
    try {
      await api.deleteBankAccount(book, a.id)
      onChange()
    } catch (err) {
      setError((err as Error).message)
    }
  }

  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm text-slate-500">
          ใส่เลขบัญชีเต็มจะจับคู่กับสลิปได้แม่นที่สุด (สลิปแสดงเลขบางหลัก เช่น xxx-x-x1234-x) · กองทุนเลือก "กองทุน A–F" แล้วใส่ชื่อจริงในชื่อเรียก
        </p>
        {canEdit && (
          <button onClick={() => setEditing('new')} className="shrink-0 rounded-lg bg-sky-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-sky-700">
            + เพิ่มบัญชี
          </button>
        )}
      </div>
      {error && <p className="rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-950/50 dark:text-red-300">{error}</p>}
      {!accounts ? (
        <p className="text-sm text-slate-500">กำลังโหลด…</p>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {accounts.map((a) => (
            <div key={a.id} className="space-y-1 rounded-2xl border border-slate-200 bg-white p-4 text-sm dark:border-slate-800 dark:bg-slate-900">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <p className="font-medium">
                    {a.nickname || a.bank_name}
                    {a.is_default && <span className="ml-1.5 rounded-full bg-sky-100 px-2 py-0.5 text-[10px] text-sky-800 dark:bg-sky-900/50 dark:text-sky-200">บัญชีหลัก</span>}
                  </p>
                  <p className="text-xs text-slate-500">
                    {a.bank_name} · {a.account_no ? a.account_no : 'ไม่ได้ใส่เลขบัญชี'}
                  </p>
                </div>
                <div className={`flex shrink-0 gap-1 ${canEdit ? '' : 'hidden'}`}>
                  <button onClick={() => setEditing(a)} className="rounded px-1.5 py-0.5 text-xs text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800">
                    แก้ไข
                  </button>
                  <button onClick={() => void remove(a)} className="rounded px-1.5 py-0.5 text-xs text-red-600 hover:bg-red-50 dark:hover:bg-red-950/50">
                    ลบ
                  </button>
                </div>
              </div>
              <p className="text-xs text-slate-500 tabular-nums">
                เงินต้น {baht.format(a.opening)} บาท ณ {thaiDate(a.opening_date)}
              </p>
              <p className="text-lg font-semibold tabular-nums">คงเหลือ {baht.format(a.balance)}</p>
            </div>
          ))}
        </div>
      )}
      <p className="text-xs text-slate-500">
        บัญชีหลัก: ใช้เมื่อพิมพ์ในกลุ่ม LINE {GROUPS[book]} โดยไม่บอกธนาคาร เช่น "{book === 'personal' ? 'จ่าย ' : ''}ค่าข้าว 120" (ถ้าบอก เช่น "{book === 'personal' ? 'จ่าย ' : ''}ค่าข้าว 120 กสิกร" จะใช้บัญชีของธนาคารนั้น)
      </p>
      {editing && (
        <PersonalAccountForm
          account={editing === 'new' ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null)
            onChange()
          }}
        />
      )}
    </section>
  )
}
