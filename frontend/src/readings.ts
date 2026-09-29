import type { DeviceStatus } from './api'

/** Data-point codes that switch a device on/off, in the order the backend prefers them. */
const POWER_CODES = ['switch_led', 'switch', 'switch_1']

export function powerCode(status: DeviceStatus): string | null {
  return POWER_CODES.find((c) => typeof status[c] === 'boolean') ?? null
}

interface Reading {
  label: string
  value: string
}

// Tuya reports many values as scaled integers; these are the common ones.
const READINGS: Record<string, { label: string; format: (v: number) => string }> = {
  cur_power: { label: 'กำลังไฟ', format: (v) => `${(v / 10).toLocaleString('th-TH')} W` },
  cur_voltage: { label: 'แรงดัน', format: (v) => `${(v / 10).toFixed(1)} V` },
  cur_current: { label: 'กระแส', format: (v) => `${v} mA` },
  va_temperature: { label: 'อุณหภูมิ', format: (v) => `${(v / 10).toFixed(1)} °C` },
  temp_current: { label: 'อุณหภูมิ', format: (v) => `${v} °C` },
  va_humidity: { label: 'ความชื้น', format: (v) => `${v} %` },
  humidity_value: { label: 'ความชื้น', format: (v) => `${v} %` },
  temp_set: { label: 'ตั้งอุณหภูมิ', format: (v) => `${v} °C` },
  bright_value_v2: { label: 'ความสว่าง', format: (v) => `${Math.round(v / 10)} %` },
}

export function readings(status: DeviceStatus): Reading[] {
  return Object.entries(READINGS)
    .filter(([code]) => typeof status[code] === 'number')
    .map(([code, r]) => ({ label: r.label, value: r.format(status[code] as number) }))
}
