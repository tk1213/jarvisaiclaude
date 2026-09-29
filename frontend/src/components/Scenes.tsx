import { useEffect, useState } from 'react'
import { api, type Scene } from '../api'

export function Scenes({ canControl }: { canControl: boolean }) {
  const [scenes, setScenes] = useState<Scene[] | null>(null)
  const [running, setRunning] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  useEffect(() => {
    api.scenes().then(setScenes, () => setScenes([]))
  }, [])

  async function run(scene: Scene) {
    setRunning(scene.scene_id)
    setMessage(null)
    try {
      await api.triggerScene(scene.scene_id)
      setMessage(`สั่ง "${scene.name}" แล้ว`)
    } catch (e) {
      setMessage((e as Error).message)
    } finally {
      setRunning(null)
    }
  }

  if (!scenes || scenes.length === 0) return null

  return (
    <section className="space-y-2">
      <h2 className="text-sm font-medium text-slate-500">Scene</h2>
      <div className="flex flex-wrap gap-2">
        {scenes.map((s) => (
          <button
            key={s.scene_id}
            disabled={!canControl || running !== null}
            onClick={() => void run(s)}
            className="rounded-full border border-slate-300 bg-white px-3.5 py-1.5 text-sm hover:border-sky-500 disabled:opacity-50 dark:border-slate-700 dark:bg-slate-900"
          >
            {running === s.scene_id ? 'กำลังสั่ง…' : s.name}
          </button>
        ))}
      </div>
      {message && <p className="text-xs text-slate-500">{message}</p>}
    </section>
  )
}
