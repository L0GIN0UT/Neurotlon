import { useEffect, useState } from 'react'

// Публичное табло: категории (ОВЗ) и резерва в ответе нет (server/scoreboard_api.py).
/** Строка топа игроков в дисциплине: очки физической + BCI секций. */
export interface BoardTop {
  rank: number
  number: number
  label: string
  points: number
  pending: boolean
}

export interface BoardTeam {
  rank: number
  number: number
  name: string
  color: string
  total: number
  /** Победы команды в понге (1 матч = 1 очко), считается на сервере. */
  duel_score: number
  /** Сумма очков команды по дисциплинам (физическая + BCI). */
  by_discipline: Record<string, number>
  sections_passed: number
  finished: boolean
  /** До 5 лучших игроков по каждой дисциплине. */
  top: Record<string, BoardTop[]>
}

export interface Scoreboard {
  teams: BoardTeam[]
}

export type Connection = 'connecting' | 'live' | 'offline'

export const STREAM_URL = '/api/v1/scoreboard/stream'
const EVENT_NAME = 'scoreboard'
const EVENT_SOURCE_CLOSED = 2
const RETRY_BASE_MS = 1000
const RETRY_MAX_MS = 10000

/** Часть EventSource, которую использует табло (в тестах подменяется). */
export interface EventSourceLike {
  readyState: number
  onerror: ((event: Event) => void) | null
  addEventListener: (type: string, listener: (event: MessageEvent<string>) => void) => void
  close: () => void
}

export type SourceFactory = (url: string) => EventSourceLike

const browserSource: SourceFactory = (url) => new EventSource(url) as unknown as EventSourceLike

export function retryDelay(attempt: number): number {
  return Math.min(RETRY_BASE_MS * 2 ** attempt, RETRY_MAX_MS)
}

function parse(text: string): Scoreboard | null {
  try {
    const data = JSON.parse(text) as Scoreboard
    return Array.isArray(data.teams) ? data : null
  } catch {
    return null
  }
}

/**
 * Подписка на поток табло. Браузер сам переподключает оборванное соединение, но после
 * ответа с ошибкой (сервер перезапускается) EventSource закрывается навсегда:
 * тогда создаём новый с нарастающей паузой. Последние данные остаются на экране.
 */
export function useScoreboard(createSource: SourceFactory = browserSource) {
  const [board, setBoard] = useState<Scoreboard | null>(null)
  const [connection, setConnection] = useState<Connection>('connecting')

  useEffect(() => {
    let source: EventSourceLike | null = null
    let timer: ReturnType<typeof setTimeout> | undefined
    let attempt = 0
    let stopped = false

    function connect() {
      const current = createSource(STREAM_URL)
      source = current
      current.addEventListener(EVENT_NAME, (event) => {
        const data = parse(event.data)
        if (!data || stopped) return
        attempt = 0
        setBoard(data)
        setConnection('live')
      })
      current.onerror = () => {
        if (stopped) return
        setConnection('offline')
        if (current.readyState === EVENT_SOURCE_CLOSED) {
          current.close()
          timer = setTimeout(connect, retryDelay(attempt))
          attempt += 1
        }
      }
    }

    connect()
    return () => {
      stopped = true
      if (timer !== undefined) clearTimeout(timer)
      source?.close()
    }
  }, [createSource])

  return { board, connection }
}
