export type DeviceStatus = Record<string, boolean | number | string>

export interface Device {
  id: number
  tuya_device_id: string
  name: string
  room: string | null
  category: string
  product_name: string
  online: boolean
  status: DeviceStatus
  control_denied: boolean
  ir_hub_id: string | null
  updated_at: string
}

export type AcMode = 'cool' | 'heat' | 'auto' | 'fan' | 'dry'
export type AcFan = 'auto' | 'low' | 'mid' | 'high'
export interface AcChange {
  power?: boolean
  mode?: AcMode
  temp?: number
  fan?: AcFan
}

export interface Scene {
  scene_id: string
  name: string
}

export interface ToolCall {
  name: string
  input: Record<string, unknown>
  ok: boolean
}

export interface ChatResponse {
  session_id: string
  reply: string
  tool_calls: ToolCall[]
}

export interface User {
  id: number
  username: string
  display_name: string
  is_admin: boolean
  can_control_devices: boolean
}

const TOKEN_KEY = 'jarvis.token'

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

export function setToken(token: string | null) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token)
    else localStorage.removeItem(TOKEN_KEY)
  } catch {
    // storage unavailable (private mode); the session just won't persist
  }
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {}
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  if (body !== undefined) headers['Content-Type'] = 'application/json'

  const res = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) })
  if (res.status === 401 && token) {
    setToken(null)
    window.dispatchEvent(new Event('jarvis:logout'))
  }
  if (!res.ok) {
    // statusText is empty over HTTP/2 (e.g. through Cloudflare), so always keep the status code.
    let detail = res.statusText || `HTTP ${res.status}`
    try {
      const data = await res.json()
      if (data.detail) detail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)
    } catch {
      // non-JSON error body
    }
    throw new ApiError(res.status, detail)
  }
  return res.status === 204 ? (undefined as T) : res.json()
}

/** Download a file the server makes (e.g. an Excel report) with the login token, saved under the server's file name. */
export async function downloadFile(path: string, fallbackName: string): Promise<void> {
  const token = getToken()
  const res = await fetch(path, { headers: token ? { Authorization: `Bearer ${token}` } : {} })
  if (!res.ok) throw new ApiError(res.status, `ดาวน์โหลดไม่สำเร็จ (HTTP ${res.status})`)
  const name = /filename="([^"]+)"/.exec(res.headers.get('content-disposition') ?? '')?.[1] ?? fallbackName
  const url = URL.createObjectURL(await res.blob())
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 10_000)
}

/** POST that returns raw bytes (e.g. audio) instead of JSON. */
async function requestBlob(path: string, body: unknown): Promise<Blob> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  const res = await fetch(path, { method: 'POST', headers, body: JSON.stringify(body) })
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      const data = await res.json()
      if (typeof data.detail === 'string') detail = `${res.status} ${data.detail}`
    } catch {
      // non-JSON error body
    }
    throw new ApiError(res.status, detail)
  }
  return res.blob()
}

export interface VoiceConfig {
  engine: 'server' | 'browser'
  voice: string | null
}

export interface DocumentRow {
  id: number
  document: string
  status: 'draft' | 'issued' | string
  serial: string | null
  customer: string | null
  grand_total: string
  channel: string
  created_at: string
}

export interface ProductRow {
  name: string
  code: string
  unit: string
  price: number
  price_includes_vat: boolean
}

export interface ProductSetItem {
  product: string
  quantity: number
  unit: string | null
  // The set's special price; null = the FlowAccount price (list_price, null when the product isn't in the list).
  unit_price: number | null
  list_price?: number | null
}

export interface ProductSetRow {
  id: number
  name: string
  customer: string | null
  description: string | null
  remarks: string | null
  items: ProductSetItem[]
}

export interface ProductSetInput {
  name: string
  description: string | null
  remarks: string | null
  items: Omit<ProductSetItem, 'list_price'>[]
}

export type EntryKind = 'income' | 'expense'

export interface AccountEntry {
  id: number
  kind: EntryKind
  date: string
  doc_no: string
  party: string
  party_tax_id: string
  party_branch: string
  party_type: 'company' | 'person'
  description: string
  category: string
  base: number
  vat: number
  total: number
  wht_rate: number
  wht: number
  full_tax_invoice: boolean
  excluded: boolean
  source: 'manual' | 'flowaccount'
  external_status: string
  created_by: string
}

export type AccountEntryInput = Omit<AccountEntry, 'id' | 'total' | 'source' | 'external_status' | 'created_by' | 'vat' | 'wht'> & {
  vat: number | null // null = 7% of base
  wht: number | null // null = base × rate
}

export interface AccountSummary {
  month: string
  sales: number
  output_vat: number
  purchases: number
  input_vat: number
  unclaimable_vat: number
  credit_brought_forward: number
  vat_payable: number
  credit_carried_forward: number
  wht_pnd3: number
  wht_pnd53: number
  wht_credit: number
  profit: number
  income_count: number
  expense_count: number
  due: { pp30: string; pp30_efiling: string; pnd: string; pnd_efiling: string }
}

export interface AccountInfo {
  flowaccount_mode: 'mock' | 'live'
  last_sync: string | null
  categories: string[]
  company: { name: string; tax_id: string; branch: string }
}

export interface LineStatus {
  configured: boolean
  linked: boolean
}

export const api = {
  login: (username: string, password: string) =>
    request<{ access_token: string }>('POST', '/auth/login', { username, password }),
  me: () => request<User>('GET', '/auth/me'),
  devices: () => request<Device[]>('GET', '/devices'),
  device: (id: number) => request<Device>('GET', `/devices/${id}`),
  sync: () => request<Device[]>('POST', '/devices/sync'),
  updateDevice: (id: number, changes: { name?: string; room?: string }) =>
    request<Device>('PATCH', `/devices/${id}`, changes),
  power: (id: number, on: boolean) => request<Device>('POST', `/devices/${id}/power`, { on }),
  setAc: (id: number, changes: AcChange) => request<Device>('POST', `/devices/${id}/ac`, changes),
  scenes: () => request<Scene[]>('GET', '/scenes'),
  triggerScene: (sceneId: string) => request<void>('POST', `/scenes/${encodeURIComponent(sceneId)}/trigger`),
  voiceConfig: () => request<VoiceConfig>('GET', '/voice/config'),
  tts: (text: string) => requestBlob('/voice/tts', { text }),
  voiceLastError: () => request<{ error: string | null }>('GET', '/voice/last-error'),
  chat: (text: string, sessionId: string | null, channel: 'dashboard' | 'voice' = 'dashboard', voice: 'female' | 'male' = 'female', images: string[] = []) =>
    request<ChatResponse>('POST', '/core/chat', { text, session_id: sessionId, channel, voice, images }),
  documents: () => request<DocumentRow[]>('GET', '/documents?limit=100'),
  products: () => request<ProductRow[]>('GET', '/products'),
  syncProducts: () => request<ProductRow[]>('POST', '/products/sync'),
  productSets: () => request<ProductSetRow[]>('GET', '/product-sets'),
  deleteProductSet: (id: number) => request<void>('DELETE', `/product-sets/${id}`),
  updateProductSet: (id: number, body: ProductSetInput) => request<ProductSetRow>('PUT', `/product-sets/${id}`, body),
  accountInfo: () => request<AccountInfo>('GET', '/account/info'),
  accountEntries: (kind: EntryKind, month: string) => request<AccountEntry[]>('GET', `/account/entries?kind=${kind}&month=${month}`),
  addAccountEntry: (body: AccountEntryInput) => request<AccountEntry>('POST', '/account/entries', body),
  editAccountEntry: (id: number, body: Partial<AccountEntryInput>) => request<AccountEntry>('PUT', `/account/entries/${id}`, body),
  deleteAccountEntry: (id: number) => request<void>('DELETE', `/account/entries/${id}`),
  syncAccount: () => request<{ added: number; updated: number; last_sync: string }>('POST', '/account/sync'),
  accountSummary: (month: string) => request<AccountSummary>('GET', `/account/summary?month=${month}`),
  lineStatus: () => request<LineStatus>('GET', '/line/status'),
  lineLinkCode: () => request<{ code: string; expires_in: number }>('POST', '/line/link-code'),
  lineUnlink: () => request<void>('DELETE', '/line/link'),
}

export function deviceStreamUrl(token: string): string {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${location.host}/ws/devices?token=${encodeURIComponent(token)}`
}
