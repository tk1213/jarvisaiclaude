import { useEffect, useState, type FormEvent } from 'react'
import { api, type AccountEntry, type EntryKind } from '../api'

const baht = new Intl.NumberFormat('th-TH', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const WHT_RATES = [0, 1, 2, 3, 5]

const round2 = (n: number) => Math.round(n * 100) / 100

/** Today when the month shown is this month, otherwise the 1st of that month. */
function defaultDate(month: string) {
  const d = new Date()
  const today = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
  return today.startsWith(month) ? today : `${month}-01`
}

/**
 * Add or edit one income/expense record. A record read from FlowAccount keeps FlowAccount's amounts:
 * only "ไม่นับ", the category, the payee type (ภ.ง.ด.3/53) and whether its VAT is claimable can change.
 */
export function AccountEntryForm({
  kind,
  entry,
  month,
  categories,
  onSaved,
  onClose,
}: {
  kind: EntryKind
  entry: AccountEntry | null
  month: string
  categories: string[]
  onSaved: (entry: AccountEntry) => void
  onClose: () => void
}) {
  const imported = entry?.source === 'flowaccount'
  const [date, setDate] = useState(() => entry?.date ?? defaultDate(month))
  const [docNo, setDocNo] = useState(entry?.doc_no ?? '')
  const [party, setParty] = useState(entry?.party ?? '')
  const [taxId, setTaxId] = useState(entry?.party_tax_id ?? '')
  const [branch, setBranch] = useState(entry?.party_branch ?? '')
  const [partyType, setPartyType] = useState<'company' | 'person'>(entry?.party_type ?? 'company')
  const [description, setDescription] = useState(entry?.description ?? '')
  const [category, setCategory] = useState(entry?.category ?? '')
  const [base, setBase] = useState(entry ? String(entry.base) : '')
  const [hasVat, setHasVat] = useState(entry ? entry.vat > 0 : true)
  const [vat, setVat] = useState(entry ? String(entry.vat) : '')
  const [vatEdited, setVatEdited] = useState(false)
  const [whtRate, setWhtRate] = useState(entry?.wht_rate ?? 0)
  const [fullTaxInvoice, setFullTaxInvoice] = useState(entry?.full_tax_invoice ?? true)
  const [excluded, setExcluded] = useState(entry?.excluded ?? false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const baseNumber = Number(base) || 0
  // VAT follows the base at 7% until it's typed by hand (a supplier's invoice can be a few satang off).
  const vatNumber = !hasVat ? 0 : vatEdited ? Number(vat) || 0 : round2(baseNumber * 0.07)
  const whtNumber = round2((baseNumber * whtRate) / 100)

  async function save(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setSaving(true)
    try {
      const body = {
        kind,
        date,
        doc_no: docNo,
        party,
        party_tax_id: taxId,
        party_branch: branch,
        party_type: partyType,
        description,
        category,
        base: baseNumber,
        vat: vatNumber,
        wht_rate: whtRate,
        wht: null,
        full_tax_invoice: kind === 'expense' ? fullTaxInvoice : true,
        excluded,
      }
      const saved = imported
        ? await api.editAccountEntry(entry.id, { excluded, category, party_type: partyType, full_tax_invoice: fullTaxInvoice })
        : entry
          ? await api.editAccountEntry(entry.id, body)
          : await api.addAccountEntry(body)
      onSaved(saved)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setSaving(false)
    }
  }

  const field =
    'w-full rounded-lg border border-slate-300 bg-transparent px-2.5 py-1.5 outline-none focus:border-sky-500 focus:ring-2 focus:ring-sky-500/30 disabled:bg-slate-50 disabled:text-slate-500 dark:border-slate-700 dark:disabled:bg-slate-800/50'
  const label = 'space-y-1'
  const caption = 'text-xs text-slate-500'
  const who = kind === 'income' ? 'ลูกค้า' : 'ผู้ขาย / ผู้รับเงิน'

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-slate-900/50 p-4 sm:items-center"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <form onSubmit={save} role="dialog" aria-modal="true" className="w-full max-w-2xl space-y-4 rounded-2xl bg-white p-5 text-sm shadow-xl dark:bg-slate-900">
        <h3 className="text-base font-semibold">
          {entry ? 'แก้ไข' : 'เพิ่ม'}
          {kind === 'income' ? 'รายรับ' : 'รายจ่าย'}
          {imported && (
            <span className="ml-2 rounded-full bg-violet-100 px-2 py-0.5 text-xs font-normal text-violet-800 dark:bg-violet-900/50 dark:text-violet-200">จาก FlowAccount</span>
          )}
        </h3>
        {imported && (
          <p className="text-xs text-slate-500">
            ยอดเงินและรายละเอียดมาจาก FlowAccount (แก้ที่ FlowAccount แล้วกดดึงข้อมูลใหม่) ที่นี่แก้ได้เฉพาะหมวด ประเภทผู้รับเงิน และการนับยอด
          </p>
        )}

        <div className="grid gap-3 sm:grid-cols-3">
          <label className={label}>
            <span className={caption}>วันที่</span>
            <input type="date" value={date} onChange={(e) => setDate(e.target.value)} required disabled={imported} className={field} />
          </label>
          <label className={label}>
            <span className={caption}>เลขที่ใบกำกับภาษี</span>
            <input value={docNo} onChange={(e) => setDocNo(e.target.value)} maxLength={64} disabled={imported} className={field} />
          </label>
          <label className={label}>
            <span className={caption}>ประเภท{who}</span>
            <select value={partyType} onChange={(e) => setPartyType(e.target.value as 'company' | 'person')} className={field}>
              <option value="company">นิติบุคคล{kind === 'expense' ? ' (ภ.ง.ด.53)' : ''}</option>
              <option value="person">บุคคลธรรมดา{kind === 'expense' ? ' (ภ.ง.ด.3)' : ''}</option>
            </select>
          </label>
        </div>

        <div className="grid gap-3 sm:grid-cols-[1fr_11rem_9rem]">
          <label className={label}>
            <span className={caption}>ชื่อ{who}</span>
            <input value={party} onChange={(e) => setParty(e.target.value)} required maxLength={256} disabled={imported} className={field} />
          </label>
          <label className={label}>
            <span className={caption}>เลขผู้เสียภาษี (13 หลัก)</span>
            <input value={taxId} onChange={(e) => setTaxId(e.target.value)} inputMode="numeric" maxLength={17} disabled={imported} className={field} />
          </label>
          <label className={label}>
            <span className={caption}>สาขา</span>
            <input value={branch} onChange={(e) => setBranch(e.target.value)} placeholder="สำนักงานใหญ่" maxLength={64} disabled={imported} className={field} />
          </label>
        </div>

        <div className={`grid gap-3 ${kind === 'expense' ? 'sm:grid-cols-[1fr_14rem]' : ''}`}>
          <label className={label}>
            <span className={caption}>รายละเอียด</span>
            <input value={description} onChange={(e) => setDescription(e.target.value)} maxLength={2000} disabled={imported} className={field} />
          </label>
          {kind === 'expense' && (
            <label className={label}>
              <span className={caption}>หมวดรายจ่าย</span>
              <select value={category} onChange={(e) => setCategory(e.target.value)} className={field}>
                <option value="">- เลือก -</option>
                {categories.map((c) => (
                  <option key={c}>{c}</option>
                ))}
              </select>
            </label>
          )}
        </div>

        <div className="grid gap-3 rounded-xl bg-slate-50 p-3 sm:grid-cols-4 dark:bg-slate-800/50">
          <label className={label}>
            <span className={caption}>ยอดก่อน VAT (บาท)</span>
            <input value={base} onChange={(e) => setBase(e.target.value)} type="number" min="0.01" step="0.01" required disabled={imported} className={field} />
          </label>
          <div className={label}>
            <label className={`flex items-center gap-1.5 ${caption}`}>
              <input type="checkbox" checked={hasVat} onChange={(e) => setHasVat(e.target.checked)} disabled={imported} />
              VAT 7%
            </label>
            <input
              value={hasVat ? (vatEdited ? vat : String(vatNumber)) : '0'}
              onChange={(e) => {
                setVatEdited(true)
                setVat(e.target.value)
              }}
              type="number"
              min="0"
              step="0.01"
              disabled={imported || !hasVat}
              aria-label="VAT"
              className={field}
            />
          </div>
          <label className={label}>
            <span className={caption}>{kind === 'income' ? 'ลูกค้าหัก ณ ที่จ่าย' : 'เราหัก ณ ที่จ่าย'}</span>
            <select value={whtRate} onChange={(e) => setWhtRate(Number(e.target.value))} disabled={imported} className={field}>
              {WHT_RATES.map((r) => (
                <option key={r} value={r}>
                  {r === 0 ? 'ไม่มี' : `${r}%  (${baht.format(round2((baseNumber * r) / 100))})`}
                </option>
              ))}
            </select>
          </label>
          <div className="space-y-1 text-right">
            <span className={caption}>รวมทั้งสิ้น</span>
            <p className="pt-1.5 text-base font-semibold tabular-nums">{baht.format(imported ? entry.total : baseNumber + vatNumber)}</p>
            {!imported && whtRate > 0 && <p className="text-xs text-slate-500 tabular-nums">รับ/จ่ายจริง {baht.format(baseNumber + vatNumber - whtNumber)}</p>}
          </div>
        </div>

        <div className="flex flex-wrap gap-x-6 gap-y-2">
          {kind === 'expense' && (
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={fullTaxInvoice} onChange={(e) => setFullTaxInvoice(e.target.checked)} />
              ได้ใบกำกับภาษีเต็มรูป (นับ VAT เป็นภาษีซื้อ)
            </label>
          )}
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={excluded} onChange={(e) => setExcluded(e.target.checked)} />
            ไม่นับรายการนี้ (เช่น เอกสารยกเลิก)
          </label>
        </div>

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
