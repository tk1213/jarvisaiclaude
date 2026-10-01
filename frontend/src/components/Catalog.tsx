import { useEffect, useState } from 'react'
import { api, type ProductRow, type ProductSetRow } from '../api'

const baht = new Intl.NumberFormat('th-TH', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

/** Products copied from FlowAccount and the named sets ("ชุด A") JARVIS quotes from. */
export function Catalog({ refreshKey }: { refreshKey: number }) {
  const [products, setProducts] = useState<ProductRow[]>([])
  const [sets, setSets] = useState<ProductSetRow[]>([])
  const [showProducts, setShowProducts] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

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

  return (
    <section className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-sm font-medium text-slate-500">สินค้าและชุดสินค้า (FlowAccount)</h2>
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
            <ul className="divide-y divide-slate-100 dark:divide-slate-800">
              {sets.map((s) => (
                <li key={s.id} className="px-4 py-2.5">
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="font-medium">
                      {s.name}
                      {s.customer && <span className="ml-2 text-xs font-normal text-slate-500">({s.customer})</span>}
                    </span>
                    <button onClick={() => void remove(s)} className="text-xs text-slate-400 hover:text-red-600">
                      ลบ
                    </button>
                  </div>
                  <ul className="mt-1 space-y-0.5 text-slate-600 dark:text-slate-300">
                    {s.items.map((i, n) => (
                      <li key={n}>
                        • {i.product} × {i.quantity} {i.unit ?? ''}
                        {i.unit_price != null && <span className="text-xs text-amber-700 dark:text-amber-300"> ราคาพิเศษ {baht.format(i.unit_price)}</span>}
                      </li>
                    ))}
                  </ul>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </section>
  )
}
