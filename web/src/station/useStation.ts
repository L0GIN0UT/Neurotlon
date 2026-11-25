import { useCallback, useEffect, useRef, useState } from 'react'
import { openStream, postCommand } from './bridge.ts'
import type { BridgeConfig, Connection } from './bridge.ts'
import type { Command, Snapshot } from './types.ts'

export interface Station {
  snapshot: Snapshot | null
  connection: Connection
  send: (command: Command) => void
  /** Текст последнего отказа ядра (400 с `error`); сбрасывается следующей командой. */
  commandError: string | null
}

/** Подписывается на состояние станции и отдаёт функцию отправки команд. */
export function useStation(config: BridgeConfig): Station {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null)
  const [connection, setConnection] = useState<Connection>('connecting')
  const [commandError, setCommandError] = useState<string | null>(null)
  const configRef = useRef(config)

  useEffect(() => {
    configRef.current = config
    return openStream(config, setSnapshot, setConnection)
  }, [config])

  const send = useCallback((command: Command) => {
    void postCommand(configRef.current, command).then((result) => {
      // команды ввода сыплются часто и без отказов: сообщение меняем только по их исходу
      setCommandError(result.error)
    })
  }, [])

  return { snapshot, connection, send, commandError }
}
