import { useState } from 'react'
import { api, type Device } from '../api'
import { powerCode, readings } from '../readings'

export function DeviceCard({ device, canControl, onUpdate }: { device: Device; canControl: boolean; onUpdate: (d: Device) => void }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showRaw, setShowRaw] = useState(false)

  const code = powerCode(device.status)
  const isOn = code ? device.status[code] === true : false
  const values = readings(device.status)

  async function toggle() {
    setBusy(true)
    setError(null)
    try {
      onUpdate(await api.power(device.id, !isOn))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <article
      className={`flex flex-col gap-3 rounded-2xl border p-4 transition-colors ${
        isOn
          ? 'border-sky-300 bg-sky-50 dark:border-sky-700 dark:bg-sky-950/40'
          : 'border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900'
      }`}
    >
      <header className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="truncate font-semibold">{device.name}</h3>
          <p className="truncate text-sm text-slate-500">{device.room ?? device.product_name}</p>
        </div>
        <span
          className={`inline-flex shrink-0 items-center gap-1.5 rounded-full px-2 py-0.5 text-xs ${
            device.online ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/50 dark:text-emerald-300' : 'bg-slate-200 text-slate-600 dark:bg-slate-800 dark:text-slate-400'
          }`}
        >
          <span className={`size-1.5 rounded-full ${device.online ? 'bg-emerald-500' : 'bg-slate-400'}`} />
          {device.online ? 'ออนไลน์' : 'ออฟไลน์'}
        </span>
      </header>

      {values.length > 0 && (
        <dl className="grid grid-cols-2 gap-2">
          {values.map((r) => (
            <div key={r.label} className="rounded-lg bg-slate-100/80 px-2.5 py-1.5 dark:bg-slate-800/60">
              <dt className="text-xs text-slate-500">{r.label}</dt>
              <dd className="font-medium tabular-nums">{r.value}</dd>
            </div>
          ))}
        </dl>
      )}

      <div className="mt-auto flex items-center justify-between gap-2">
        {code ? (
          <button
            role="switch"
            aria-checked={isOn}
            aria-label={`${isOn ? 'ปิด' : 'เปิด'} ${device.name}`}
            disabled={busy || !device.online || !canControl}
            onClick={toggle}
            className={`relative h-7 w-12 rounded-full transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
              isOn ? 'bg-sky-600' : 'bg-slate-300 dark:bg-slate-700'
            }`}
          >
            <span className={`absolute top-0.5 left-0.5 size-6 rounded-full bg-white shadow transition-transform ${isOn ? 'translate-x-5' : ''}`} />
          </button>
        ) : (
          <span className="text-xs text-slate-500">สั่งงานผ่าน JARVIS</span>
        )}
        <button onClick={() => setShowRaw((v) => !v)} className="text-xs text-slate-500 hover:text-slate-800 dark:hover:text-slate-200">
          {showRaw ? 'ซ่อนรายละเอียด' : 'รายละเอียด'}
        </button>
      </div>

      {error && <p className="text-xs text-red-600 dark:text-red-400">{error}</p>}
      {showRaw && (
        <pre className="max-h-48 overflow-auto rounded-lg bg-slate-100 p-2 text-xs dark:bg-slate-800">
          {JSON.stringify(device.status, null, 2)}
        </pre>
      )}
    </article>
  )
}
