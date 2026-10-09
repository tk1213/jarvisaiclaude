import { useCallback, useEffect, useState } from 'react'
import { api, type BankAccount, type PersonalEntry, type PersonalSummary } from '../api'
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

/** 💳 Personal money: balances per bank or fund account, income and expenses (also from the LINE group "tk รับจ่าย"), and the accounts. */
export function Personal() {
  const [tab, setTab] = useState<Tab>('balance')
  const [month, setMonth] = useState(thisMonth)
  const [accounts, setAccounts] = useState<BankAccount[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [version, setVersion] = useState(0)

  useEffect(() => {
    api.bankAccounts().then(setAccounts, (e) => setError((e as Error).message))
  }, [version])

  const changed = () => setVersion((v) => v + 1)

  return (
    <main className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-semibold">การเงินส่วนตัว</h2>
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
          ยังไม่มีบัญชีธนาคาร{' '}
          <button onClick={() => setTab('accounts')} className="text-sky-700 underline dark:text-sky-300">
            เพิ่มบัญชีธนาคาร
          </button>{' '}
          พร้อมเงินต้นก่อน แล้วค่อยส่งสลิปในกลุ่ม LINE "tk รับจ่าย"
        </div>
      ) : tab === 'balance' ? (
        <Balances month={month} version={version} />
      ) : tab === 'accounts' ? (
        <Accounts accounts={accounts} onChange={changed} />
      ) : (
        <Entries key={tab} kind={tab} month={month} accounts={accounts ?? []} version={version} onChange={changed} />
      )}
    </main>
  )
}

function Balances({ month, version }: { month: string; version: number }) {
  const [data, setData] = useState<PersonalSummary | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.personalSummary(month).then(setData, (e) => setError((e as Error).message))
  }, [month, version])

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
  onChange,
}: {
  kind: 'income' | 'expense'
  month: string
  accounts: BankAccount[]
  version: number
  onChange: () => void
}) {
  const [accountId, setAccountId] = useState(0)
  const [rows, setRows] = useState<PersonalEntry[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [editing, setEditing] = useState<PersonalEntry | 'new' | null>(null)
  const [slip, setSlip] = useState<PersonalEntry | null>(null)

  const load = useCallback(() => {
    api.personalEntries(kind, month, accountId || undefined).then(setRows, (e) => setError((e as Error).message))
  }, [kind, month, accountId])
  useEffect(load, [load, version])

  async function remove(e: PersonalEntry) {
    if (!window.confirm(`ลบรายการ ${baht.format(e.amount)} บาท วันที่ ${thaiDate(e.date)} ?${e.has_slip ? ' (รูปสลิปจะถูกลบด้วย)' : ''}`)) return
    try {
      await api.deletePersonalEntry(e.id)
      onChange()
    } catch (err) {
      setError((err as Error).message)
    }
  }

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
        <button onClick={() => setEditing('new')} className="rounded-lg bg-sky-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-sky-700">
          + เพิ่ม{word}
        </button>
      </div>
      {error && <p className="rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-950/50 dark:text-red-300">{error}</p>}

      <div className="overflow-x-auto rounded-2xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
        <table className="w-full min-w-[48rem] text-sm">
          <thead className="bg-slate-50 text-xs text-slate-500 dark:bg-slate-800/60">
            <tr>
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
                    <button onClick={() => setEditing(r)} className="rounded px-1.5 py-0.5 text-xs text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800">
                      แก้ไข
                    </button>
                    <button onClick={() => void remove(r)} className="rounded px-1.5 py-0.5 text-xs text-red-600 hover:bg-red-50 dark:hover:bg-red-950/50">
                      ลบ
                    </button>
                  </td>
                </tr>
              )
            })}
            {rows?.length === 0 && (
              <tr>
                <td colSpan={6} className="px-3 py-8 text-center text-slate-500">
                  ยังไม่มี{word}ในเดือนนี้ ส่งสลิปในกลุ่ม LINE "tk รับจ่าย" หรือกด "+ เพิ่ม{word}"
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

function Accounts({ accounts, onChange }: { accounts: BankAccount[] | null; onChange: () => void }) {
  const [editing, setEditing] = useState<BankAccount | 'new' | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function remove(a: BankAccount) {
    if (!window.confirm(`ลบบัญชี ${a.label} ?`)) return
    setError(null)
    try {
      await api.deleteBankAccount(a.id)
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
        <button onClick={() => setEditing('new')} className="shrink-0 rounded-lg bg-sky-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-sky-700">
          + เพิ่มบัญชี
        </button>
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
                <div className="flex shrink-0 gap-1">
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
        บัญชีหลัก: ใช้เมื่อพิมพ์ในกลุ่ม LINE "tk รับจ่าย" โดยไม่บอกธนาคาร เช่น "จ่าย ค่าข้าว 120" (ถ้าบอก เช่น "จ่าย ค่าข้าว 120 กสิกร" จะใช้บัญชีของธนาคารนั้น)
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
