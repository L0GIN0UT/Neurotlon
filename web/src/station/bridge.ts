import type { Command, Snapshot } from './types.ts'

/** Куда обращаться к лаунчеру: адрес и токен запуска. */
export interface BridgeConfig {
  url: string
  token: string
}

declare global {
  interface Window {
    /** Кладёт окно Electron (preload): окружение интерфейса не видит токен нигде, кроме этого. */
    stationBridge?: BridgeConfig
  }
}

/** Настройки моста: из Electron, иначе из адреса `?port=…&token=…` (разработка в браузере). */
export function readBridgeConfig(win: Pick<Window, 'stationBridge' | 'location'>): BridgeConfig | null {
  if (win.stationBridge) return win.stationBridge
  const params = new URLSearchParams(win.location.search)
  const port = params.get('port')
  const token = params.get('token')
  if (!port || !token || !/^\d{2,5}$/.test(port)) return null
  return { url: `http://127.0.0.1:${port}`, token }
}

export async function sendCommand(config: BridgeConfig, command: Command): Promise<boolean> {
  try {
    const response = await fetch(`${config.url}/api/command`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Station-Token': config.token },
      body: JSON.stringify(command),
    })
    return response.ok
  } catch {
    return false
  }
}

export type Connection = 'connecting' | 'live' | 'lost'

/**
 * Подписка на снимки. EventSource сам переподключается; `onConnection` сообщает о связи,
 * чтобы интерфейс мог показать «Нет связи с лаунчером», а не молча замереть.
 */
export function openStream(
  config: BridgeConfig,
  onSnapshot: (snapshot: Snapshot) => void,
  onConnection: (state: Connection) => void,
): () => void {
  const source = new EventSource(`${config.url}/api/events?token=${encodeURIComponent(config.token)}`)
  source.onopen = () => onConnection('live')
  source.onerror = () => onConnection(source.readyState === EventSource.CLOSED ? 'lost' : 'connecting')
  source.onmessage = (event: MessageEvent<string>) => {
    try {
      onSnapshot(JSON.parse(event.data) as Snapshot)
      onConnection('live')
    } catch {
      // повреждённый кадр пропускаем: следующий снимок полный
    }
  }
  return () => source.close()
}
