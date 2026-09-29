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
  updated_at: string
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
    let detail = res.statusText
    try {
      const data = await res.json()
      detail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)
    } catch {
      // non-JSON error body
    }
    throw new ApiError(res.status, detail)
  }
  return res.status === 204 ? (undefined as T) : res.json()
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
  scenes: () => request<Scene[]>('GET', '/scenes'),
  triggerScene: (sceneId: string) => request<void>('POST', `/scenes/${encodeURIComponent(sceneId)}/trigger`),
  chat: (text: string, sessionId: string | null) =>
    request<ChatResponse>('POST', '/core/chat', { text, session_id: sessionId }),
}

export function deviceStreamUrl(token: string): string {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${location.host}/ws/devices?token=${encodeURIComponent(token)}`
}
