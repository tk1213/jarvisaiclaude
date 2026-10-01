import { useEffect, useState } from 'react'
import { api, type DocumentRow } from '../api'

const baht = new Intl.NumberFormat('th-TH', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

/** Recent FlowAccount documents JARVIS drafted or issued (refreshes after each chat reply). */
export function Documents({ refreshKey }: { refreshKey: number }) {
  const [rows, setRows] = useState<DocumentRow[] | null>(null)

  useEffect(() => {
    api.documents().then(setRows, () => setRows([]))
  }, [refreshKey])

  if (!rows) return null
  if (rows.length === 0)
    return (
      <section className="space-y-2">
        <h2 className="text-sm font-medium text-slate-500">เอกสารล่าสุด</h2>
        <p className="rounded-2xl border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500 dark:border-slate-700">
          ยังไม่มีเอกสาร ลองสั่งจาร์วิส เช่น "ออกใบเสนอราคา บริษัท เอ ชุด A"
        </p>
      </section>
    )

  return (
    <section className="space-y-2">
      <h2 className="text-sm font-medium text-slate-500">เอกสารล่าสุด</h2>
      <ul className="divide-y divide-slate-200 rounded-2xl border border-slate-200 bg-white text-sm dark:divide-slate-800 dark:border-slate-800 dark:bg-slate-900">
        {rows.map((d) => (
          <li key={d.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5">
            <span
              className={`rounded-full px-2 py-0.5 text-xs ${
                d.status === 'issued'
                  ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/50 dark:text-emerald-200'
                  : d.status === 'cancelled'
                    ? 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300'
                    : 'bg-amber-100 text-amber-800 dark:bg-amber-900/50 dark:text-amber-200'
              }`}
            >
              {d.status === 'issued' ? 'ออกแล้ว' : d.status === 'cancelled' ? 'ยกเลิก' : 'ร่าง รอยืนยัน'}
            </span>
            <span className="font-medium">{d.document}</span>
            {d.serial && <span className="font-mono text-xs text-slate-500">{d.serial}</span>}
            <span className="min-w-0 flex-1 truncate text-slate-600 dark:text-slate-300">{d.customer}</span>
            <span className="tabular-nums">{baht.format(Number(d.grand_total))} บาท</span>
            <span className="text-xs text-slate-400">{d.channel === 'line' ? 'LINE' : d.channel === 'voice' ? 'เสียง' : 'แชท'}</span>
          </li>
        ))}
      </ul>
    </section>
  )
}
