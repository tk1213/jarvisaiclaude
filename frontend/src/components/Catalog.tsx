import { useEffect, useState, type PointerEvent } from 'react'
import { api, type ProductRow, type ProductSetRow } from '../api'
import { SetEditor } from './SetEditor'

const baht = new Intl.NumberFormat('th-TH', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

/** Products copied from FlowAccount and the named sets ("ชุด A") JARVIS quotes from. */
export function Catalog({ refreshKey }: { refreshKey: number }) {
  const [products, setProducts] = useState<ProductRow[]>([])
  const [sets, setSets] = useState<ProductSetRow[]>([])
  const [showProducts, setShowProducts] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  // The set whose item list pops up (mouse hover, or a tap on a phone), and the one open in the editor.
  const [peek, setPeek] = useState<{ id: number; right: boolean } | null>(null)
  const [editing, setEditing] = useState<ProductSetRow | null>(null)

  useEffect(() => {
    api.products().then(setProducts, () => {})
    api.productSets().then(setSets, () => {})
  }, [refreshKey])

  async function sync() {
    setSyncing(true)
    setMessage(null)
    try {
      const rows = await api.syncProducts()
      setProducts(rows)
      setMessage(`อัปเดตแล้ว มีสินค้า ${rows.length} รายการ`)
    } catch (e) {
      setMessage((e as Error).message)
    } finally {
      setSyncing(false)
    }
  }

  async function remove(set: ProductSetRow) {
    if (!window.confirm(`ลบ "${set.name}" ?`)) return
    await api.deleteProductSet(set.id)
    setSets((s) => s.filter((x) => x.id !== set.id))
  }

  function show(e: PointerEvent<HTMLElement>, id: number) {
    // Open the pop-up towards the side with room, so it never runs off the screen.
    const rect = e.currentTarget.getBoundingClientRect()
    setPeek({ id, right: rect.left + 320 > window.innerWidth })
  }

  return (
    <section className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-sm font-medium text-slate-500">สินค้าและชุดสินค้า</h2>
        <button
          onClick={() => void sync()}
          disabled={syncing}
          className="rounded-lg border border-slate-300 px-2.5 py-1 text-xs hover:border-sky-500 disabled:opacity-50 dark:border-slate-700"
        >
          {syncing ? 'กำลังอัปเดต…' : 'อัปเดตสินค้า'}
        </button>
      </div>
      {message && <p className="text-xs text-slate-500">{message}</p>}
      <div className="rounded-2xl border border-slate-200 bg-white text-sm dark:border-slate-800 dark:bg-slate-900">
        <button onClick={() => setShowProducts(!showProducts)} className="flex w-full items-center justify-between px-4 py-2.5 text-left">
          <span>สินค้า {products.length} รายการ</span>
          <span className="text-xs text-slate-400">{showProducts ? 'ซ่อน' : 'ดูทั้งหมด'}</span>
        </button>
        {showProducts && (
          <ul className="divide-y divide-slate-100 border-t border-slate-200 dark:divide-slate-800 dark:border-slate-800">
            {products.map((p) => (
              <li key={p.code + p.name} className="flex gap-3 px-4 py-1.5">
                <span className="w-20 shrink-0 font-mono text-xs text-slate-400">{p.code}</span>
                <span className="min-w-0 flex-1 truncate">{p.name}</span>
                <span className="tabular-nums">
                  {baht.format(p.price)}/{p.unit || 'หน่วย'}
                  {p.price_includes_vat && <span className="text-xs text-slate-400"> รวม VAT</span>}
                </span>
              </li>
            ))}
            {products.length === 0 && <li className="px-4 py-2 text-slate-500">ยังไม่มี กด "อัปเดตสินค้า" เพื่อดึงจาก FlowAccount</li>}
          </ul>
        )}
        <div className="border-t border-slate-200 dark:border-slate-800">
          {sets.length === 0 ? (
            <p className="px-4 py-2.5 text-slate-500">ยังไม่มีชุดสินค้า บอกจาร์วิสได้เลย เช่น "บันทึกชุด A: โช๊ค GUTE 1 เมตร 2 ตัว, โช๊ค GUTE 1.5 เมตร 3 ตัว"</p>
          ) : (
            <div className="grid grid-cols-2 gap-2 p-3 sm:grid-cols-3 lg:grid-cols-4">
              {sets.map((s) => (
                <div
                  key={s.id}
                  className="relative rounded-xl border border-slate-200 p-3 hover:border-sky-400 dark:border-slate-700"
                  onPointerEnter={(e) => e.pointerType === 'mouse' && show(e, s.id)}
                  onPointerLeave={(e) => e.pointerType === 'mouse' && setPeek(null)}
                >
                  <button
                    type="button"
                    onPointerUp={(e) => e.pointerType !== 'mouse' && (peek?.id === s.id ? setPeek(null) : show(e, s.id))}
                    aria-expanded={peek?.id === s.id}
                    className="block w-full text-left"
                  >
                    <span className="block font-medium">{s.name}</span>
                    <span className={`mt-0.5 line-clamp-2 text-xs ${s.description ? 'text-slate-600 dark:text-slate-300' : 'text-slate-400'}`}>
                      {s.description || 'ยังไม่มีคำอธิบาย'}
                    </span>
                  </button>
                  <div className="mt-2 flex gap-3 text-xs">
                    <button onClick={() => setEditing(s)} className="text-sky-700 hover:underline dark:text-sky-300">
                      ✏️ แก้ไข
                    </button>
                    <button onClick={() => void remove(s)} className="text-slate-400 hover:text-red-600">
                      ลบ
                    </button>
                  </div>
                  {peek?.id === s.id && <SetPopup set={s} alignRight={peek.right} />}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
      {editing && (
        <SetEditor
          set={editing}
          products={products}
          onClose={() => setEditing(null)}
          onSaved={(saved) => {
            setSets((current) => current.map((x) => (x.id === saved.id ? saved : x)).sort((a, b) => a.name.localeCompare(b.name, 'th')))
            setEditing(null)
            setMessage(`บันทึก ${saved.name} แล้ว`)
          }}
        />
      )}
    </section>
  )
}

/** A set's items with the price each one will be quoted at, its total before VAT and its หมายเหตุ. */
function SetPopup({ set, alignRight }: { set: ProductSetRow; alignRight: boolean }) {
  const price = (i: ProductSetRow['items'][number]) => i.unit_price ?? i.list_price ?? null
  const total = set.items.reduce((sum, i) => sum + i.quantity * (price(i) ?? 0), 0)
  return (
    // pt-1 instead of a margin: the pointer can move onto the pop-up without leaving the card.
    <div className={`absolute top-full z-20 w-80 max-w-[85vw] pt-1 ${alignRight ? 'right-0' : 'left-0'}`}>
      <div role="tooltip" className="space-y-2 rounded-xl border border-slate-200 bg-white p-3 text-xs shadow-lg dark:border-slate-700 dark:bg-slate-900">
        <ul className="space-y-1">
          {set.items.map((i, n) => (
            <li key={n} className="flex gap-2">
              <span className="min-w-0 flex-1">
                {i.product} × {i.quantity} {i.unit ?? ''}
              </span>
              <span className={`shrink-0 tabular-nums ${i.unit_price != null ? 'text-amber-700 dark:text-amber-300' : ''}`}>
                {price(i) != null ? `${baht.format(price(i)!)}/${i.unit || 'หน่วย'}` : 'ไม่มีราคา'}
                {i.unit_price != null && ' (พิเศษ)'}
              </span>
            </li>
          ))}
        </ul>
        <p className="border-t border-slate-100 pt-1.5 text-right font-medium tabular-nums dark:border-slate-800">รวม {baht.format(total)} บาท (ก่อน VAT)</p>
        {set.customer && <p className="text-slate-500">ลูกค้า: {set.customer}</p>}
        {set.remarks && <p className="whitespace-pre-wrap text-slate-500">หมายเหตุ: {set.remarks}</p>}
      </div>
    </div>
  )
}
