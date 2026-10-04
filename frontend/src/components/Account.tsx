import { useCallback, useEffect, useState } from 'react'
import { api, downloadFile, type AccountEntry, type AccountInfo, type AccountSummary, type EntryKind } from '../api'
import { AccountEntryForm } from './AccountEntryForm'

const baht = new Intl.NumberFormat('th-TH', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const THAI_MONTHS = ['ม.ค.', 'ก.พ.', 'มี.ค.', 'เม.ย.', 'พ.ค.', 'มิ.ย.', 'ก.ค.', 'ส.ค.', 'ก.ย.', 'ต.ค.', 'พ.ย.', 'ธ.ค.']

type Tab = EntryKind | 'summary'
const TABS: { id: Tab; label: string }[] = [
  { id: 'income', label: 'รายรับ' },
  { id: 'expense', label: 'รายจ่าย' },
  { id: 'summary', label: 'สรุปภาษี' },
]

function thisMonth() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

/** "2026-11-15" -> "15 พ.ย. 2569" */
function thaiDate(iso: string) {
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number)
  return `${d} ${THAI_MONTHS[m - 1]} ${y + 543}`
}

function shiftMonth(month: string, by: number) {
  const [y, m] = month.split('-').map(Number)
  const d = new Date(y, m - 1 + by, 1)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

/** The Account page: income and expense records for tax, read from FlowAccount or typed in, and the monthly tax summary. */
export function Account() {
  const [tab, setTab] = useState<Tab>('income')
  const [month, setMonth] = useState(thisMonth)
  const [info, setInfo] = useState<AccountInfo | null>(null)
  const [syncing, setSyncing] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [version, setVersion] = useState(0)

  useEffect(() => {
    api.accountInfo().then(setInfo, (e) => setMessage((e as Error).message))
  }, [version])

  async function sync() {
    setSyncing(true)
    setMessage(null)
    try {
      const r = await api.syncAccount()
      setMessage(`ดึงข้อมูลจาก FlowAccount แล้ว: เพิ่มใหม่ ${r.added} รายการ อัปเดต ${r.updated} รายการ`)
      setVersion((v) => v + 1)
    } catch (e) {
      setMessage((e as Error).message)
    } finally {
      setSyncing(false)
    }
  }

  return (
    <main className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-semibold">บัญชีรายรับ-รายจ่าย และภาษี</h2>
        <div className="flex items-center gap-2 text-sm">
          <button
            onClick={() => setMonth(shiftMonth(month, -1))}
            aria-label="เดือนก่อน"
            className="rounded-lg border border-slate-300 px-2 py-1 hover:border-sky-500 dark:border-slate-700"
          >
            ‹
          </button>
          <input
            type="month"
            value={month}
            onChange={(e) => e.target.value && setMonth(e.target.value)}
            aria-label="เดือน"
            className="rounded-lg border border-slate-300 bg-transparent px-2 py-1 dark:border-slate-700"
          />
          <button
            onClick={() => setMonth(shiftMonth(month, 1))}
            aria-label="เดือนถัดไป"
            className="rounded-lg border border-slate-300 px-2 py-1 hover:border-sky-500 dark:border-slate-700"
          >
            ›
          </button>
          <button
            onClick={() => void sync()}
            disabled={syncing}
            className="rounded-lg border border-slate-300 px-3 py-1 hover:border-sky-500 disabled:opacity-50 dark:border-slate-700"
          >
            {syncing ? 'กำลังดึงข้อมูล…' : 'ดึงข้อมูลจาก FlowAccount'}
          </button>
        </div>
      </div>
      <p className="text-xs text-slate-500">
        {info?.last_sync ? `ดึงจาก FlowAccount ล่าสุด ${new Date(info.last_sync).toLocaleString('th-TH')}` : 'ยังไม่เคยดึงข้อมูลจาก FlowAccount'}
        {info?.flowaccount_mode === 'mock' && ' · โหมดทดลอง (FLOWACCOUNT_MODE=mock) ข้อมูลที่ดึงมาเป็นตัวอย่าง'}
      </p>
      {message && (
        <p role="status" className="flex items-start justify-between gap-3 rounded-lg bg-sky-50 p-3 text-sm text-sky-900 dark:bg-sky-950/50 dark:text-sky-200">
          {message}
          <button onClick={() => setMessage(null)} aria-label="ปิด">
            ✕
          </button>
        </p>
      )}

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

      {tab === 'summary' ? (
        <Summary month={month} version={version} />
      ) : (
        <Entries key={tab} kind={tab} month={month} version={version} categories={info?.categories ?? []} onChange={() => setVersion((v) => v + 1)} />
      )}
    </main>
  )
}

function Entries({ kind, month, version, categories, onChange }: { kind: EntryKind; month: string; version: number; categories: string[]; onChange: () => void }) {
  const [rows, setRows] = useState<AccountEntry[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [editing, setEditing] = useState<AccountEntry | 'new' | null>(null)

  const load = useCallback(() => {
    api.accountEntries(kind, month).then(setRows, (e) => setError((e as Error).message))
  }, [kind, month])
  useEffect(load, [load, version])

  async function remove(e: AccountEntry) {
    if (!window.confirm(`ลบรายการ ${e.party} ${baht.format(e.total)} บาท ?`)) return
    try {
      await api.deleteAccountEntry(e.id)
      onChange()
    } catch (err) {
      setError((err as Error).message)
    }
  }

  const counted = (rows ?? []).filter((r) => !r.excluded)
  const sum = (key: 'base' | 'vat' | 'total' | 'wht') => counted.reduce((s, r) => s + r[key], 0)
  const income = kind === 'income'

  return (
    <section className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm text-slate-500">
          {rows ? `${counted.length} รายการ` : 'กำลังโหลด…'}
          {rows && rows.length > counted.length && ` (ไม่นับ ${rows.length - counted.length})`}
        </p>
        <button onClick={() => setEditing('new')} className="rounded-lg bg-sky-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-sky-700">
          + เพิ่ม{income ? 'รายรับ' : 'รายจ่าย'}
        </button>
      </div>
      {error && <p className="rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-950/50 dark:text-red-300">{error}</p>}

      <div className="overflow-x-auto rounded-2xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
        <table className="w-full min-w-[56rem] text-sm">
          <thead className="bg-slate-50 text-xs text-slate-500 dark:bg-slate-800/60">
            <tr>
              <th className="px-3 py-2 text-left font-medium">วันที่</th>
              <th className="px-3 py-2 text-left font-medium">เลขที่</th>
              <th className="px-3 py-2 text-left font-medium">{income ? 'ลูกค้า' : 'ผู้ขาย / ผู้รับเงิน'}</th>
              <th className="px-3 py-2 text-left font-medium">{income ? 'รายละเอียด' : 'หมวด / รายละเอียด'}</th>
              <th className="px-3 py-2 text-right font-medium">ก่อน VAT</th>
              <th className="px-3 py-2 text-right font-medium">VAT</th>
              <th className="px-3 py-2 text-right font-medium">รวม</th>
              <th className="px-3 py-2 text-right font-medium">หัก ณ ที่จ่าย</th>
              <th className="px-3 py-2" />
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
            {rows?.map((r) => (
              <tr key={r.id} className={r.excluded ? 'text-slate-400 line-through decoration-slate-300' : ''}>
                <td className="px-3 py-2 whitespace-nowrap">{thaiDate(r.date)}</td>
                <td className="px-3 py-2 font-mono text-xs">{r.doc_no || '-'}</td>
                <td className="px-3 py-2">
                  {r.party}
                  {r.source === 'flowaccount' && (
                    <span className="ml-1.5 rounded-full bg-violet-100 px-1.5 py-0.5 text-[10px] text-violet-800 no-underline dark:bg-violet-900/50 dark:text-violet-200">
                      FlowAccount
                    </span>
                  )}
                  {!income && r.wht > 0 && <span className="ml-1.5 text-[10px] text-slate-500">{r.party_type === 'person' ? 'ภ.ง.ด.3' : 'ภ.ง.ด.53'}</span>}
                </td>
                <td className="max-w-[16rem] px-3 py-2 text-slate-600 dark:text-slate-300">
                  {!income && r.category && <span className="mr-1.5 rounded bg-slate-100 px-1.5 text-xs dark:bg-slate-800">{r.category}</span>}
                  <span className="line-clamp-1">{r.description}</span>
                </td>
                <td className="px-3 py-2 text-right tabular-nums">{baht.format(r.base)}</td>
                <td className="px-3 py-2 text-right tabular-nums">
                  {baht.format(r.vat)}
                  {!income && r.vat > 0 && !r.full_tax_invoice && (
                    <span title="ไม่มีใบกำกับภาษีเต็มรูป ขอคืน VAT ไม่ได้" className="block text-[10px] text-amber-700 dark:text-amber-300">
                      ขอคืนไม่ได้
                    </span>
                  )}
                </td>
                <td className="px-3 py-2 text-right font-medium tabular-nums">{baht.format(r.total)}</td>
                <td className="px-3 py-2 text-right tabular-nums">{r.wht > 0 ? `${baht.format(r.wht)} (${r.wht_rate}%)` : '-'}</td>
                <td className="px-3 py-2 text-right whitespace-nowrap">
                  <button onClick={() => setEditing(r)} className="text-xs text-sky-700 hover:underline dark:text-sky-300">
                    แก้ไข
                  </button>
                  {r.source === 'manual' && (
                    <button onClick={() => void remove(r)} className="ml-3 text-xs text-slate-400 hover:text-red-600">
                      ลบ
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {rows?.length === 0 && (
              <tr>
                <td colSpan={9} className="px-3 py-6 text-center text-slate-500">
                  ยังไม่มี{income ? 'รายรับ' : 'รายจ่าย'}เดือนนี้ กด "ดึงข้อมูลจาก FlowAccount" หรือ "+ เพิ่ม{income ? 'รายรับ' : 'รายจ่าย'}"
                </td>
              </tr>
            )}
          </tbody>
          {counted.length > 0 && (
            <tfoot className="border-t border-slate-200 font-semibold dark:border-slate-700">
              <tr>
                <td colSpan={4} className="px-3 py-2 text-right">
                  รวมเดือนนี้
                </td>
                <td className="px-3 py-2 text-right tabular-nums">{baht.format(sum('base'))}</td>
                <td className="px-3 py-2 text-right tabular-nums">{baht.format(sum('vat'))}</td>
                <td className="px-3 py-2 text-right tabular-nums">{baht.format(sum('total'))}</td>
                <td className="px-3 py-2 text-right tabular-nums">{baht.format(sum('wht'))}</td>
                <td />
              </tr>
            </tfoot>
          )}
        </table>
      </div>

      {editing && (
        <AccountEntryForm
          kind={kind}
          entry={editing === 'new' ? null : editing}
          month={month}
          categories={categories}
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

function Summary({ month, version }: { month: string; version: number }) {
  const [s, setS] = useState<AccountSummary | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.accountSummary(month).then(setS, (e) => setError((e as Error).message))
  }, [month, version])

  async function download(kind: EntryKind) {
    try {
      await downloadFile(`/account/report?month=${month}&kind=${kind}`, `${kind === 'income' ? 'sales' : 'purchase'}-tax-${month}.xlsx`)
    } catch (e) {
      setError((e as Error).message)
    }
  }

  if (error) return <p className="rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-950/50 dark:text-red-300">{error}</p>
  if (!s) return <p className="text-sm text-slate-500">กำลังคำนวณ…</p>

  const row = (label: string, value: number, opts: { strong?: boolean; minus?: boolean; note?: string } = {}) => (
    <div className={`flex items-baseline justify-between gap-3 py-1 ${opts.strong ? 'border-t border-slate-200 pt-2 font-semibold dark:border-slate-700' : ''}`}>
      <span className={opts.strong ? '' : 'text-slate-600 dark:text-slate-300'}>
        {label}
        {opts.note && <span className="block text-xs font-normal text-slate-400">{opts.note}</span>}
      </span>
      <span className="tabular-nums">
        {opts.minus && value > 0 ? '− ' : ''}
        {baht.format(value)}
      </span>
    </div>
  )
  const card = 'space-y-1 rounded-2xl border border-slate-200 bg-white p-4 text-sm dark:border-slate-800 dark:bg-slate-900'
  const due = (date: string, efiling: string) => (
    <p className="pt-1 text-xs text-slate-500">
      ยื่นภายใน {thaiDate(date)} (ยื่นออนไลน์ได้ถึง {thaiDate(efiling)})
    </p>
  )
  const pnd = s.wht_pnd3 + s.wht_pnd53

  return (
    <section className="space-y-4">
      <div className="grid gap-4 md:grid-cols-2">
        <div className={card}>
          <h3 className="pb-1 font-semibold">ภ.พ.30 ภาษีมูลค่าเพิ่ม</h3>
          {row('ภาษีขาย', s.output_vat, { note: `จากยอดขาย ${baht.format(s.sales)} บาท (${s.income_count} รายการ)` })}
          {row('ภาษีซื้อที่ขอคืนได้', s.input_vat, { minus: true, note: `จากยอดซื้อ ${baht.format(s.purchases)} บาท (${s.expense_count} รายการ)` })}
          {s.credit_brought_forward > 0 && row('ภาษีซื้อเกินยกมาจากเดือนก่อน', s.credit_brought_forward, { minus: true })}
          {s.credit_carried_forward > 0
            ? row('ภาษีซื้อเกิน ยกไปเดือนหน้า', s.credit_carried_forward, { strong: true, note: 'เดือนนี้ไม่ต้องชำระ VAT (ยังต้องยื่นแบบ ภ.พ.30)' })
            : row('VAT ที่ต้องชำระ', s.vat_payable, { strong: true })}
          {due(s.due.pp30, s.due.pp30_efiling)}
          {s.unclaimable_vat > 0 && (
            <p className="text-xs text-amber-700 dark:text-amber-300">VAT {baht.format(s.unclaimable_vat)} บาท จากรายจ่ายที่ไม่มีใบกำกับภาษีเต็มรูป ขอคืนไม่ได้</p>
          )}
        </div>

        <div className={card}>
          <h3 className="pb-1 font-semibold">ภาษีหัก ณ ที่จ่ายที่ต้องนำส่ง</h3>
          {row('ภ.ง.ด.53 (จ่ายให้นิติบุคคล)', s.wht_pnd53)}
          {row('ภ.ง.ด.3 (จ่ายให้บุคคลธรรมดา)', s.wht_pnd3)}
          {row('รวมที่ต้องนำส่ง', pnd, { strong: true })}
          {pnd > 0 ? due(s.due.pnd, s.due.pnd_efiling) : <p className="pt-1 text-xs text-slate-500">เดือนนี้ไม่มีภาษีหัก ณ ที่จ่ายที่ต้องนำส่ง</p>}
        </div>

        <div className={card}>
          <h3 className="pb-1 font-semibold">ภาพรวมเดือนนี้ (ก่อน VAT)</h3>
          {row('รายรับ', s.sales)}
          {row('รายจ่าย', s.purchases + s.unclaimable_vat, { minus: true })}
          {row('กำไรเบื้องต้น', s.profit, { strong: true, note: 'ยังไม่หักค่าเสื่อมราคาและรายการปรับปรุงทางบัญชี' })}
        </div>

        <div className={card}>
          <h3 className="pb-1 font-semibold">ภาษีที่ลูกค้าหัก ณ ที่จ่ายไว้</h3>
          {row('ยอดเดือนนี้', s.wht_credit, { strong: true })}
          <p className="pt-1 text-xs text-slate-500">ใช้เป็นเครดิตภาษีตอนยื่น ภ.ง.ด.50 (สิ้นปี) เก็บหนังสือรับรองการหักภาษี ณ ที่จ่าย (50 ทวิ) จากลูกค้าไว้ด้วย</p>
        </div>
      </div>

      <div className="flex flex-wrap gap-2">
        <button onClick={() => void download('income')} className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm hover:border-sky-500 dark:border-slate-700">
          ⬇ รายงานภาษีขาย (Excel)
        </button>
        <button onClick={() => void download('expense')} className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm hover:border-sky-500 dark:border-slate-700">
          ⬇ รายงานภาษีซื้อ (Excel)
        </button>
      </div>
      <p className="text-xs text-slate-500">
        ยอดนี้ช่วยเตรียมข้อมูลก่อนยื่นแบบผ่าน e-Filing ของกรมสรรพากร (efiling.rd.go.th) หรือส่งให้นักบัญชีตรวจ วันครบกำหนดที่ตรงวันหยุดเลื่อนเป็นวันทำการถัดไป
      </p>
    </section>
  )
}
