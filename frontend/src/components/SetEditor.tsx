import { useEffect, useState, type FormEvent } from 'react'
import { api, type ProductRow, type ProductSetRow } from '../api'

const baht = new Intl.NumberFormat('th-TH', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

interface Row {
  product: string
  quantity: string
  unit: string
  unit_price: string // '' = use the FlowAccount price
}

/** The ✏️ window for one set: name, description, remarks, and its items with quantities and special prices. */
export function SetEditor({
  set,
  products,
  onSaved,
  onClose,
}: {
  set: ProductSetRow
  products: ProductRow[]
  onSaved: (set: ProductSetRow) => void
  onClose: () => void
}) {
  const [name, setName] = useState(set.name)
  const [description, setDescription] = useState(set.description ?? '')
  const [remarks, setRemarks] = useState(set.remarks ?? '')
  const [rows, setRows] = useState<Row[]>(() =>
    set.items.map((i) => ({ product: i.product, quantity: String(i.quantity), unit: i.unit ?? '', unit_price: i.unit_price == null ? '' : String(i.unit_price) })),
  )
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const byName = new Map(products.map((p) => [p.name, p]))

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  function change(index: number, patch: Partial<Row>) {
    setRows((current) =>
      current.map((row, i) => {
        if (i !== index) return row
        const next = { ...row, ...patch }
        // Picking a product from the list fills in its unit.
        const product = patch.product !== undefined ? byName.get(patch.product) : undefined
        if (product && !row.unit) next.unit = product.unit
        return next
      }),
    )
  }

  function price(row: Row): number | null {
    if (row.unit_price.trim() !== '') return Number(row.unit_price)
    return byName.get(row.product)?.price ?? null
  }

  const total = rows.reduce((sum, r) => sum + (Number(r.quantity) || 0) * (price(r) ?? 0), 0)

  async function save(e: FormEvent) {
    e.preventDefault()
    setError(null)
    const items = rows.filter((r) => r.product.trim())
    if (items.length === 0) return setError('ชุดต้องมีสินค้าอย่างน้อย 1 รายการ')
    if (items.some((r) => !(Number(r.quantity) > 0))) return setError('จำนวนต้องมากกว่า 0')
    if (items.some((r) => r.unit_price.trim() !== '' && !(Number(r.unit_price) >= 0))) return setError('ราคาต้องเป็นตัวเลขไม่ติดลบ')
    setSaving(true)
    try {
      const saved = await api.updateProductSet(set.id, {
        name: name.trim(),
        description: description.trim() || null,
        remarks: remarks.trim() || null,
        items: items.map((r) => ({
          product: r.product.trim(),
          quantity: Number(r.quantity),
          unit: r.unit.trim() || null,
          unit_price: r.unit_price.trim() === '' ? null : Number(r.unit_price),
        })),
      })
      onSaved(saved)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setSaving(false)
    }
  }

  const field = 'rounded-lg border border-slate-300 bg-transparent px-2.5 py-1.5 outline-none focus:border-sky-500 focus:ring-2 focus:ring-sky-500/30 dark:border-slate-700'

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-slate-900/50 p-4 sm:items-center" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <form
        onSubmit={save}
        role="dialog"
        aria-modal="true"
        aria-label={`แก้ไข ${set.name}`}
        className="w-full max-w-2xl space-y-4 rounded-2xl bg-white p-5 text-sm shadow-xl dark:bg-slate-900"
      >
        <h3 className="text-base font-semibold">แก้ไข {set.name}</h3>

        <div className="grid gap-3 sm:grid-cols-[10rem_1fr]">
          <label className="space-y-1">
            <span className="text-xs text-slate-500">ชื่อชุด</span>
            <input value={name} onChange={(e) => setName(e.target.value)} required maxLength={128} className={`w-full ${field}`} />
          </label>
          <label className="space-y-1">
            <span className="text-xs text-slate-500">คำอธิบายชุด (แสดงบนช่อง ไม่ลงในเอกสาร)</span>
            <input value={description} onChange={(e) => setDescription(e.target.value)} maxLength={200} placeholder="เช่น โช๊คประตูบ้านเดี่ยว" className={`w-full ${field}`} />
          </label>
        </div>

        <div className="space-y-2">
          <div className="hidden gap-2 text-xs text-slate-500 sm:flex">
            <span className="flex-1">สินค้า</span>
            <span className="w-20">จำนวน</span>
            <span className="w-20">หน่วย</span>
            <span className="w-36">ราคาพิเศษ/หน่วย</span>
            <span className="w-7" />
          </div>
          <datalist id="set-editor-products">
            {products.map((p) => (
              <option key={p.code + p.name} value={p.name} />
            ))}
          </datalist>
          {rows.map((row, i) => {
            const listed = byName.get(row.product)
            return (
              <div key={i} className="flex flex-wrap items-center gap-2 border-b border-slate-100 pb-2 sm:flex-nowrap sm:border-0 sm:pb-0 dark:border-slate-800">
                <input
                  value={row.product}
                  onChange={(e) => change(i, { product: e.target.value })}
                  list="set-editor-products"
                  placeholder="พิมพ์หรือเลือกสินค้า"
                  aria-label={`สินค้ารายการที่ ${i + 1}`}
                  className={`min-w-0 basis-full sm:flex-1 sm:basis-auto ${field}`}
                />
                <input
                  value={row.quantity}
                  onChange={(e) => change(i, { quantity: e.target.value })}
                  type="number"
                  min="0"
                  step="any"
                  aria-label="จำนวน"
                  className={`w-20 ${field}`}
                />
                <input value={row.unit} onChange={(e) => change(i, { unit: e.target.value })} aria-label="หน่วย" placeholder="หน่วย" className={`w-20 ${field}`} />
                <input
                  value={row.unit_price}
                  onChange={(e) => change(i, { unit_price: e.target.value })}
                  type="number"
                  min="0"
                  step="0.01"
                  aria-label="ราคาพิเศษต่อหน่วย"
                  placeholder={listed ? `${baht.format(listed.price)} (FA)` : 'ไม่มีราคา'}
                  title="เว้นว่าง = ใช้ราคาจาก FlowAccount"
                  className={`w-36 ${field} ${row.unit_price ? 'text-amber-700 dark:text-amber-300' : ''}`}
                />
                <button
                  type="button"
                  onClick={() => setRows(rows.filter((_, j) => j !== i))}
                  aria-label={`ลบรายการที่ ${i + 1}`}
                  className="grid size-7 shrink-0 place-items-center rounded-full text-slate-400 hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-950/50"
                >
                  ✕
                </button>
              </div>
            )
          })}
          <div className="flex flex-wrap items-center justify-between gap-2">
            <button
              type="button"
              onClick={() => setRows([...rows, { product: '', quantity: '1', unit: '', unit_price: '' }])}
              className="rounded-lg border border-dashed border-slate-300 px-3 py-1.5 text-xs hover:border-sky-500 dark:border-slate-700"
            >
              + เพิ่มสินค้า
            </button>
            <span className="text-xs text-slate-500">
              ราคาพิเศษเว้นว่าง = ใช้ราคาจาก FlowAccount · รวม {baht.format(total)} บาท (ก่อน VAT)
            </span>
          </div>
        </div>

        <label className="block space-y-1">
          <span className="text-xs text-slate-500">หมายเหตุ (ลงในช่องหมายเหตุของเอกสารที่ใช้ชุดนี้)</span>
          <textarea value={remarks} onChange={(e) => setRemarks(e.target.value)} rows={3} maxLength={2000} className={`w-full ${field}`} />
        </label>

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
