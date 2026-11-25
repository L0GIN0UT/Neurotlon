import { AnimatePresence } from 'motion/react'
import { useEffect, useMemo, useState } from 'react'
import { readBridgeConfig } from './bridge.ts'
import type { BridgeConfig } from './bridge.ts'
import { CalibrationScreen } from './CalibrationScreen.tsx'
import { ConfirmScreen } from './ConfirmScreen.tsx'
import { Backdrop, BottomBar, TopBar } from './Frame.tsx'
import { commandForKey, screenKey } from './flow.ts'
import { accentFor, accentStyle, RESULT_STEP, stepOf } from './model.ts'
import { ScanScreen } from './ScanScreen.tsx'
import { Screen } from './Screen.tsx'
import { SetupScreen } from './SetupScreen.tsx'
import type { Direction } from './Screen.tsx'
import {
  BlockedScreen,
  BusyScreen,
  DoneScreen,
  PlayingScreen,
  ProblemScreen,
  RejectedScreen,
} from './StatusScreens.tsx'
import * as t from './texts.ts'
import type { Command, Snapshot } from './types.ts'
import { useStation } from './useStation.ts'
import './station.css'

function Body({
  snapshot,
  config,
  send,
}: {
  snapshot: Snapshot
  config: BridgeConfig
  send: (command: Command) => void
}) {
  const { state, discipline, players_needed: playersNeeded } = snapshot
  switch (state.kind) {
    case 'idle':
      return (
        <ScanScreen
          input={state.input}
          notice={state.notice}
          taken={state.taken}
          playersNeeded={playersNeeded}
          camera={snapshot.camera ?? null}
          send={send}
        />
      )
    case 'checking':
      return <BusyScreen title={t.CHECKING} players={state.taken} send={send} />
    case 'confirm':
      return (
        <ConfirmScreen
          config={config}
          candidate={state.candidate}
          taken={state.taken}
          notice={state.notice}
          isLast={state.is_last}
          discipline={discipline}
          playersNeeded={playersNeeded}
          send={send}
        />
      )
    case 'starting':
      return <BusyScreen title={t.STARTING} hint={t.STARTING_HINT} players={state.players} send={send} />
    case 'calibrating':
      return <CalibrationScreen state={state} config={config} send={send} />
    case 'playing':
      return (
        <PlayingScreen
          players={state.players}
          discipline={discipline}
          offline={state.offline}
          defaultLimit={state.default_limit}
          send={send}
        />
      )
    case 'done':
      return (
        <DoneScreen
          lines={state.lines}
          secondsLeft={state.seconds_left}
          secondsTotal={state.seconds_total}
        />
      )
    case 'problem':
      return <ProblemScreen reason={state.reason} send={send} />
    case 'blocked':
      return <BlockedScreen message={state.message} />
    case 'rejected':
      return <RejectedScreen items={state.items} exportedTo={state.exported_to} send={send} />
    case 'setup':
      return <SetupScreen state={state} send={send} />
  }
}

function Connected({ config }: { config: BridgeConfig }) {
  const { snapshot, connection, send } = useStation(config)
  const kind = snapshot?.state.kind

  useEffect(() => {
    if (!snapshot) return
    const onKey = (event: KeyboardEvent) => {
      if (event.ctrlKey || event.altKey || event.metaKey) return
      // Enter на сфокусированной второстепенной кнопке нажимает её, а не «Дальше».
      if (
        snapshot.state.kind === 'calibrating' &&
        event.key === 'Enter' &&
        event.target instanceof HTMLButtonElement &&
        event.target.dataset.primary === undefined
      ) {
        return
      }
      const command = commandForKey(snapshot.state, event.key)
      if (command) {
        event.preventDefault()
        send(command)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [snapshot, send])

  // Вперёд по шагам экран уезжает влево, назад («Это не я») — вправо; после «Готово» снова вперёд.
  const step = kind ? stepOf(kind) : null
  const [nav, setNav] = useState<{ step: number | null; direction: Direction }>({
    step: null,
    direction: 1,
  })
  if (step !== null && step !== nav.step) {
    const back = nav.step !== null && nav.step !== RESULT_STEP && step < nav.step
    setNav({ step, direction: back ? -1 : 1 })
  }
  const direction = nav.direction

  const accent = accentFor(snapshot?.discipline ?? '')
  return (
    <div className="station" style={accentStyle(accent)}>
      <Backdrop discipline={snapshot?.discipline ?? ''} />
      <TopBar snapshot={snapshot} connection={connection} />
      <main className="stage">
        <AnimatePresence custom={direction}>
          {snapshot && (
            <Screen key={screenKey(snapshot.state)} direction={direction}>
              <Body snapshot={snapshot} config={config} send={send} />
            </Screen>
          )}
        </AnimatePresence>
      </main>
      <BottomBar snapshot={snapshot} onShowRejected={() => send({ action: 'show_rejected' })} />
    </div>
  )
}

/** Интерфейс стенда: рисует состояние лаунчера, команды отправляет ему же. */
export function StationApp() {
  const config = useMemo(() => readBridgeConfig(window), [])
  if (!config) {
    return (
      <div className="station" style={accentStyle(accentFor(''))}>
        <main className="stage">
          <section className="screen center">
            <h1 className="big">{t.BRIDGE_LOST}</h1>
            <p className="lead">Окно открыто без лаунчера: запустите стенд через Electron.</p>
          </section>
        </main>
      </div>
    )
  }
  return <Connected config={config} />
}
