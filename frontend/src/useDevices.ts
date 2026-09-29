import { useCallback, useEffect, useRef, useState } from 'react'
import { api, deviceStreamUrl, getToken, type Device } from './api'

type StreamEvent = { type: 'device'; device: Device } | { type: 'device_removed'; id: number }

export type LinkState = 'connecting' | 'live' | 'offline'

/** Device list kept current by the /ws/devices stream, reconnecting with backoff. */
export function useDevices() {
  const [devices, setDevices] = useState<Device[]>([])
  const [link, setLink] = useState<LinkState>('connecting')
  const [error, setError] = useState<string | null>(null)
  const retry = useRef(0)

  const upsert = useCallback((d: Device) => {
    setDevices((prev) => {
      const i = prev.findIndex((p) => p.id === d.id)
      if (i === -1) return [...prev, d].sort((a, b) => a.id - b.id)
      const next = prev.slice()
      next[i] = d
      return next
    })
  }, [])

  const reload = useCallback(async () => {
    try {
      setDevices(await api.devices())
      setError(null)
    } catch (e) {
      setError((e as Error).message)
    }
  }, [])

  useEffect(() => {
    let ws: WebSocket | null = null
    let timer: number | undefined
    let stopped = false

    const connect = () => {
      const token = getToken()
      if (!token || stopped) return
      ws = new WebSocket(deviceStreamUrl(token))
      ws.onopen = () => {
        retry.current = 0
        setLink('live')
        void reload() // catch anything that changed while disconnected
      }
      ws.onmessage = (msg) => {
        const event = JSON.parse(msg.data) as StreamEvent
        if (event.type === 'device') upsert(event.device)
        else setDevices((prev) => prev.filter((d) => d.id !== event.id))
      }
      ws.onclose = (e) => {
        setLink('offline')
        if (stopped || e.code === 4401) return
        void reload() // still show devices when the live stream can't connect
        const delay = Math.min(30_000, 1000 * 2 ** retry.current++)
        timer = window.setTimeout(() => {
          setLink('connecting')
          connect()
        }, delay)
      }
    }

    connect() // onopen loads the list
    return () => {
      stopped = true
      window.clearTimeout(timer)
      ws?.close()
    }
  }, [reload, upsert])

  return { devices, link, error, reload, upsert, setDevices }
}
