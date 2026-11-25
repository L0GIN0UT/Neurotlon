import { useEffect, useState } from 'react'
import type { BridgeConfig } from './bridge.ts'
import { parseBatch, SignalStore } from './calibration.ts'

const RECONNECT_MS = 1000

/** Адрес потока сигналов: тот же источник и токен, что у `/api/events`. */
export const signalsUrl = (config: BridgeConfig): string =>
  `${config.url}/api/signals?token=${encodeURIComponent(config.token)}`

export interface SignalStream {
  /** Буферы живут вне состояния React: график читает их сам, экран на каждое значение не перерисовывается. */
  store: SignalStore
  /** Идёт ли поток прямо сейчас. */
  connected: boolean
}

/**
 * Подписывается на `/api/signals`, пока экран открыт, и складывает кадры в буфер.
 * При обрыве, который не лечит сам EventSource, переоткрывает поток; при выходе закрывает его.
 */
export function useSignalStream(config: BridgeConfig): SignalStream {
  const [store] = useState(() => new SignalStore())
  const [connected, setConnected] = useState(false)

  useEffect(() => {
    let source: EventSource | null = null
    let timer: ReturnType<typeof setTimeout> | undefined
    let stopped = false

    const open = () => {
      const next = new EventSource(signalsUrl(config))
      source = next
      next.onopen = () => setConnected(true)
      next.onerror = () => {
        setConnected(false)
        if (next.readyState === EventSource.CLOSED && !stopped) {
          timer = setTimeout(open, RECONNECT_MS)
        }
      }
      next.onmessage = (event: MessageEvent<string>) => {
        const now = performance.now()
        store.apply(parseBatch(event.data), now)
        setConnected(true)
      }
    }
    open()

    return () => {
      stopped = true
      clearTimeout(timer)
      source?.close()
      store.clear()
    }
  }, [config, store])

  return { store, connected }
}
