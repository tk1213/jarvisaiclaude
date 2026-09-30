import { useState } from 'react'
import { api, type AcChange, type AcFan, type AcMode, type Device } from '../api'

// Numeric codes reported by Tuya for IR air conditioners.
const MODES: { key: AcMode; code: number; label: string }[] = [
  { key: 'cool', code: 0, label: 'เย็น' },
  { key: 'heat', code: 1, label: 'ร้อน' },
  { key: 'auto', code: 2, label: 'อัตโนมัติ' },
  { key: 'fan', code: 3, label: 'พัดลม' },
  { key: 'dry', code: 4, label: 'แห้ง' },
]
const FANS: { key: AcFan; code: number; label: string }[] = [
  { key: 'auto', code: 0, label: 'อัตโนมัติ' },
  { key: 'low', code: 1, label: 'เบา' },
  { key: 'mid', code: 2, label: 'กลาง' },
  { key: 'high', code: 3, label: 'แรง' },
]
const MIN_TEMP = 16
const MAX_TEMP = 30

/** Mode, temperature and fan controls for an IR air conditioner (category infrared_ac). */
export function AcControls({ device, disabled, onUpdate }: { device: Device; disabled: boolean; onUpdate: (d: Device) => void }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const mode = Number(device.status.mode ?? 0)
  const temp = Number(device.status.temperature ?? 25)
  const fan = Number(device.status.fan ?? 0)
  const locked = disabled || busy

  async function send(change: AcChange) {
    setBusy(true)
    setError(null)
    try {
      onUpdate(await api.setAc(device.id, change))
    } catch (e) {
      const message = (e as Error).message
      if (message.toLowerCase().includes('permission')) onUpdate(await api.device(device.id))
      else setError(message)
    } finally {
      setBusy(false)
    }
  }

  const chip = (active: boolean) =>
    `rounded-full px-2.5 py-1 text-xs transition-colors disabled:opacity-50 ${
      active ? 'bg-sky-600 text-white' : 'bg-slate-100 text-slate-700 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700'
    }`

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between rounded-xl bg-slate-100/80 px-3 py-2 dark:bg-slate-800/60">
        <button
          aria-label="ลดอุณหภูมิ"
          disabled={locked || temp <= MIN_TEMP}
          onClick={() => void send({ temp: temp - 1 })}
          className="size-9 rounded-full bg-white text-lg font-medium shadow-sm hover:bg-slate-50 disabled:opacity-40 dark:bg-slate-700 dark:hover:bg-slate-600"
        >
          −
        </button>
        <div className="text-center">
          <div className="text-2xl font-semibold tabular-nums">{temp}°C</div>
          <div className="text-xs text-slate-500">ตั้งอุณหภูมิ</div>
        </div>
        <button
          aria-label="เพิ่มอุณหภูมิ"
          disabled={locked || temp >= MAX_TEMP}
          onClick={() => void send({ temp: temp + 1 })}
          className="size-9 rounded-full bg-white text-lg font-medium shadow-sm hover:bg-slate-50 disabled:opacity-40 dark:bg-slate-700 dark:hover:bg-slate-600"
        >
          +
        </button>
      </div>

      <div className="space-y-1">
        <p className="text-xs text-slate-500">โหมด</p>
        <div className="flex flex-wrap gap-1.5">
          {MODES.map((m) => (
            <button key={m.key} disabled={locked} aria-pressed={mode === m.code} onClick={() => void send({ mode: m.key })} className={chip(mode === m.code)}>
              {m.label}
            </button>
          ))}
        </div>
      </div>

      <div className="space-y-1">
        <p className="text-xs text-slate-500">ความแรงลม</p>
        <div className="flex flex-wrap gap-1.5">
          {FANS.map((f) => (
            <button key={f.key} disabled={locked} aria-pressed={fan === f.code} onClick={() => void send({ fan: f.key })} className={chip(fan === f.code)}>
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {!device.ir_hub_id && <p className="text-xs text-amber-700 dark:text-amber-300">ยังไม่รู้จักตัวส่ง IR ของแอร์นี้ กด "อัปเดตอุปกรณ์" ก่อน</p>}
      {error && <p className="text-xs text-red-600 dark:text-red-400">{error}</p>}
    </div>
  )
}
