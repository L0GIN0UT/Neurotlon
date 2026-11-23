import { useCallback, useEffect, useRef, useState } from 'react'
import { openStream, sendCommand } from './bridge.ts'
import type { BridgeConfig, Connection } from './bridge.ts'
import type { Command, Snapshot } from './types.ts'

export interface Station {
  snapshot: Snapshot | null
  connection: Connection
  send: (command: Command) => void
}

/** Подписывается на состояние станции и отдаёт функцию отправки команд. */
export function useStation(config: BridgeConfig): Station {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null)
  const [connection, setConnection] = useState<Connection>('connecting')
  const configRef = useRef(config)

  useEffect(() => {
    configRef.current = config
    return openStream(config, setSnapshot, setConnection)
  }, [config])

  const send = useCallback((command: Command) => {
    void sendCommand(configRef.current, command)
  }, [])

  return { snapshot, connection, send }
}
