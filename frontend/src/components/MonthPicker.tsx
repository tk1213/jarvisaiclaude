import { shiftMonth } from '../months'

/** ‹ month › with a native month input in the middle. */
export function MonthPicker({ month, onChange }: { month: string; onChange: (month: string) => void }) {
  const button = 'rounded-lg border border-slate-300 px-2 py-1 hover:border-sky-500 dark:border-slate-700'
  return (
    <div className="flex items-center gap-2">
      <button onClick={() => onChange(shiftMonth(month, -1))} aria-label="เดือนก่อน" className={button}>
        ‹
      </button>
      <input
        type="month"
        value={month}
        onChange={(e) => e.target.value && onChange(e.target.value)}
        aria-label="เดือน"
        className="rounded-lg border border-slate-300 bg-transparent px-2 py-1 dark:border-slate-700"
      />
      <button onClick={() => onChange(shiftMonth(month, 1))} aria-label="เดือนถัดไป" className={button}>
        ›
      </button>
    </div>
  )
}
