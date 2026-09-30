import { useState, type FormEvent } from 'react'
import { api, type Device } from '../api'
import { powerCode, readings } from '../readings'
import { AcControls } from './AcControls'

interface Props {
  device: Device
  canControl: boolean
  rooms: string[]
  onUpdate: (d: Device) => void
}

export function DeviceCard({ device, canControl, rooms, onUpdate }: Props) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showRaw, setShowRaw] = useState(false)
  const [editing, setEditing] = useState(false)

  const code = powerCode(device.status)
  const isOn = code ? device.status[code] === true : false
  const values = readings(device.status)

  async function toggle() {
    setBusy(true)
    setError(null)
    try {
      onUpdate(await api.power(device.id, !isOn))
    } catch (e) {
      if ((e as Error).message.toLowerCase().includes('permission')) {
        // Shown as the banner instead; reload so control_denied is current even without the live stream.
        onUpdate(await api.device(device.id))
      } else {
        setError((e as Error).message)
      }
    } finally {
      setBusy(false)
    }
  }

  if (editing) {
    return (
      <EditForm
        device={device}
        rooms={rooms}
        onCancel={() => setEditing(false)}
        onSaved={(d) => {
          onUpdate(d)
          setEditing(false)
        }}
      />
    )
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
          <div className="flex items-center gap-1">
            <h3 className="truncate font-semibold">{device.name}</h3>
            {canControl && (
              <button
                onClick={() => setEditing(true)}
                aria-label={`แก้ไข ${device.name}`}
                title="แก้ไขชื่อ/ห้อง"
                className="shrink-0 rounded p-1 text-slate-400 hover:bg-slate-200 hover:text-slate-700 dark:hover:bg-slate-800 dark:hover:text-slate-200"
              >
                <svg viewBox="0 0 20 20" fill="currentColor" className="size-3.5" aria-hidden="true">
                  <path d="M13.6 3.3a1.5 1.5 0 0 1 2.1 0l1 1a1.5 1.5 0 0 1 0 2.1l-8.8 8.8-3.5.9.9-3.5 8.3-8.3Z" />
                </svg>
              </button>
            )}
          </div>
          <p className="truncate text-sm text-slate-500">{device.room ?? 'ยังไม่ระบุห้อง'}</p>
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

      {device.control_denied && (
        <div role="alert" className="rounded-lg bg-amber-50 p-2.5 text-xs text-amber-900 dark:bg-amber-950/50 dark:text-amber-200">
          <p className="font-medium">ยังสั่งงานไม่ได้: Tuya ให้สิทธิ์แค่อ่านค่า</p>
          <p className="mt-0.5">
            ที่ iot.tuya.com &gt; Cloud &gt; โปรเจกต์ &gt; Devices เปลี่ยน Device Permission ของอุปกรณ์นี้เป็น <b>Controllable</b> แล้วลองใหม่
          </p>
        </div>
      )}

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

      {device.category === 'infrared_ac' && (
        <AcControls device={device} disabled={!device.online || !canControl || !isOn} onUpdate={onUpdate} />
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
          <span className="text-xs text-slate-500">{device.category === 'wnykq' ? 'ตัวส่งสัญญาณ IR' : 'สั่งงานผ่าน JARVIS'}</span>
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

function EditForm({ device, rooms, onCancel, onSaved }: { device: Device; rooms: string[]; onCancel: () => void; onSaved: (d: Device) => void }) {
  const [name, setName] = useState(device.name)
  const [room, setRoom] = useState(device.room ?? '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const listId = `rooms-${device.id}`

  async function save(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      onSaved(await api.updateDevice(device.id, { name: name.trim(), room: room.trim() }))
    } catch (err) {
      setError((err as Error).message)
      setBusy(false)
    }
  }

  const input =
    'w-full rounded-lg border border-slate-300 bg-transparent px-3 py-1.5 outline-none focus:border-sky-500 focus:ring-2 focus:ring-sky-500/30 dark:border-slate-700'

  return (
    <form onSubmit={save} className="flex flex-col gap-3 rounded-2xl border border-sky-400 bg-white p-4 dark:border-sky-600 dark:bg-slate-900">
      <label className="block space-y-1">
        <span className="text-xs font-medium text-slate-500">ชื่ออุปกรณ์</span>
        <input className={input} value={name} onChange={(e) => setName(e.target.value)} maxLength={128} required autoFocus />
      </label>
      <label className="block space-y-1">
        <span className="text-xs font-medium text-slate-500">ห้อง</span>
        <input className={input} value={room} onChange={(e) => setRoom(e.target.value)} list={listId} maxLength={64} placeholder="เช่น ห้องนอน (เว้นว่างได้)" />
        <datalist id={listId}>
          {rooms.map((r) => (
            <option key={r} value={r} />
          ))}
        </datalist>
      </label>
      <p className="text-xs text-slate-500">รุ่น: {device.product_name || device.tuya_device_id}</p>
      {error && <p className="text-xs text-red-600 dark:text-red-400">{error}</p>}
      <div className="mt-auto flex justify-end gap-2">
        <button type="button" onClick={onCancel} className="rounded-lg px-3 py-1.5 text-sm text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800">
          ยกเลิก
        </button>
        <button disabled={busy || !name.trim()} className="rounded-lg bg-sky-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-sky-700 disabled:opacity-50">
          {busy ? 'กำลังบันทึก…' : 'บันทึก'}
        </button>
      </div>
    </form>
  )
}
