import { LayoutGroup, motion } from 'motion/react'
import type { ReactNode } from 'react'
import { DisciplineIcon } from '../shared/icons/DisciplineIcon.tsx'
import logo from './assets/logo.png'
import type { Connection } from './bridge.ts'
import { Icon } from './Icon.tsx'
import type { IconName } from './Icon.tsx'
import { hintsFor, stepOf } from './model.ts'
import * as t from './texts.ts'
import type { Snapshot, StateView } from './types.ts'

/** Фон: градиент со свечением цвета дисциплины и крупным значком-«постером». */
export function Backdrop({ discipline }: { discipline: string }) {
  return (
    <div className="backdrop" aria-hidden>
      <div className="glow glow-a" />
      <div className="glow glow-b" />
      <div className="poster">
        <DisciplineIcon discipline={discipline} />
      </div>
    </div>
  )
}

export function Chip({
  tone,
  icon,
  children,
}: {
  tone: 'good' | 'warn' | 'bad' | 'muted'
  icon?: IconName | 'dot'
  children: ReactNode
}) {
  return (
    <span className={`chip chip-${tone}`}>
      {icon === 'dot' ? <i className="dot" /> : icon && <Icon name={icon} />}
      <span>{children}</span>
    </span>
  )
}

function LinkChip({ snapshot, connection }: { snapshot: Snapshot | null; connection: Connection }) {
  if (connection === 'lost') return <Chip tone="bad" icon="offline">{t.BRIDGE_LOST}</Chip>
  const online = snapshot?.status.online
  if (online === true) return <Chip tone="good" icon="dot">{t.LINK.live}</Chip>
  if (online === false) return <Chip tone="warn" icon="offline">{t.LINK.lost}</Chip>
  return <Chip tone="muted" icon="dot">{t.LINK.unknown}</Chip>
}

function Steps({ current }: { current: number }) {
  return (
    <ol className="steps" aria-label="Шаги">
      {t.STEPS.map((label, i) => {
        const state = i < current ? 'done' : i === current ? 'active' : 'todo'
        return (
          <li key={label} className={`step step-${state}`} aria-current={state === 'active' ? 'step' : undefined}>
            {state === 'active' && (
              <motion.span layoutId="step-pill" className="step-pill" transition={{ type: 'spring', visualDuration: 0.45, bounce: 0.2 }} />
            )}
            <span className="step-mark">{state === 'done' ? <Icon name="check" /> : i + 1}</span>
            <span className="step-label">{label}</span>
          </li>
        )
      })}
    </ol>
  )
}

export function TopBar({ snapshot, connection }: { snapshot: Snapshot | null; connection: Connection }) {
  const step = snapshot ? stepOf(snapshot.state.kind) : null
  return (
    <header className="topbar">
      <img className="brand-logo" src={logo} alt={`${t.BRAND} · ${t.BRAND_SUB}`} />
      <LayoutGroup>{step !== null && <Steps current={step} />}</LayoutGroup>
      <div className="topbar-right">
        {snapshot?.sensors && !snapshot.sensors.ok && (
          <span title={snapshot.sensors.error ?? undefined}>
            <Chip tone="bad" icon="warning">
              {t.SENSORS_DOWN}
            </Chip>
          </span>
        )}
        <LinkChip snapshot={snapshot} connection={connection} />
      </div>
    </header>
  )
}

export function BottomBar({
  snapshot,
  onShowRejected,
}: {
  snapshot: Snapshot | null
  onShowRejected: () => void
}) {
  const kind: StateView['kind'] | null = snapshot?.state.kind ?? null
  const hints = snapshot ? hintsFor(snapshot.state) : []
  const status = snapshot?.status
  return (
    <footer className="bottombar">
      <div className="hints">
        {hints.map(([key, label]) => (
          <span key={key} className="hint">
            <kbd>{key}</kbd>
            {label}
          </span>
        ))}
      </div>
      <div className="queue">
        {status && status.pending > 0 && <Chip tone="warn">{t.QUEUE(status.pending)}</Chip>}
        {status && status.rejected > 0 && kind !== 'rejected' && (
          <button type="button" className="chip-button" onClick={onShowRejected}>
            <Chip tone="bad" icon="warning">{t.REJECTED_CHIP(status.rejected)}</Chip>
          </button>
        )}
      </div>
    </footer>
  )
}
