export const baht = new Intl.NumberFormat('th-TH', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const THAI_MONTHS = ['ม.ค.', 'ก.พ.', 'มี.ค.', 'เม.ย.', 'พ.ค.', 'มิ.ย.', 'ก.ค.', 'ส.ค.', 'ก.ย.', 'ต.ค.', 'พ.ย.', 'ธ.ค.']

export function thisMonth() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

/** "2026-11-15" -> "15 พ.ย. 2569" */
export function thaiDate(iso: string) {
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number)
  return `${d} ${THAI_MONTHS[m - 1]} ${y + 543}`
}

/** "2026-11" -> "พ.ย. 2569" */
export function thaiMonth(month: string) {
  const [y, m] = month.split('-').map(Number)
  return `${THAI_MONTHS[m - 1]} ${y + 543}`
}

export function shiftMonth(month: string, by: number) {
  const [y, m] = month.split('-').map(Number)
  const d = new Date(y, m - 1 + by, 1)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

/** Today when the month shown is this month, otherwise the 1st of that month. */
export function defaultDate(month: string) {
  const d = new Date()
  const today = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
  return today.startsWith(month) ? today : `${month}-01`
}
