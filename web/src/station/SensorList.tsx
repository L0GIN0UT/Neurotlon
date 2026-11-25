import { useEffect, useId, useRef, useState } from 'react'
import type { KeyboardEvent } from 'react'
import { Icon } from './Icon.tsx'
import { Notice } from './Notice.tsx'
import * as t from './texts.ts'
import { linkStatus, rssiBars } from './sensorModel.ts'
import type { Command, SensorEntry, SensorsView } from './types.ts'

const IDLE: SensorsView = { phase: 'idle', error: null, devices: [] }

function RssiBars({ rssi }: { rssi: number | null }) {
  const bars = rssiBars(rssi)
  const text = t.SETUP.sensorsRssi(bars, rssi)
  return (
    <span className="rssi" role="img" aria-label={text} title={text}>
      {[1, 2, 3, 4].map((n) => (
        <span key={n} className={n <= bars ? 'on' : ''} style={{ height: `${0.5 + n * 0.35}rem` }} />
      ))}
    </span>
  )
}

/** Меню выбора роли: стрелки, Home/End, Enter; Esc возвращает фокус на кнопку. */
function RoleMenu({
  label,
  roles,
  onPick,
  disabled,
}: {
  label: string
  roles: string[]
  onPick: (role: string) => void
  disabled: boolean
}) {
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLDivElement>(null)
  const button = useRef<HTMLButtonElement>(null)
  const items = useRef<(HTMLButtonElement | null)[]>([])
  const menuId = useId()

  useEffect(() => {
    if (!open) return
    items.current[0]?.focus()
    const close = (event: PointerEvent) => {
      if (root.current && !root.current.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('pointerdown', close)
    return () => document.removeEventListener('pointerdown', close)
  }, [open])

  const move = (index: number) => items.current[(index + roles.length) % roles.length]?.focus()
  const onKeyDown = (event: KeyboardEvent<HTMLUListElement>) => {
    const index = items.current.findIndex((el) => el === document.activeElement)
    switch (event.key) {
      case 'ArrowDown':
        event.preventDefault()
        move(index + 1)
        break
      case 'ArrowUp':
        event.preventDefault()
        move(index - 1)
        break
      case 'Home':
        event.preventDefault()
        move(0)
        break
      case 'End':
        event.preventDefault()
        move(roles.length - 1)
        break
      case 'Escape':
        event.preventDefault()
        event.stopPropagation()
        setOpen(false)
        button.current?.focus()
        break
      case 'Tab':
        setOpen(false)
        break
    }
  }

  return (
    <div className="role-menu" ref={root}>
      <button
        ref={button}
        type="button"
        className="setup-action sensor-connect"
        aria-haspopup="menu"
        aria-expanded={open}
        disabled={disabled}
        aria-controls={open ? menuId : undefined}
        onClick={() => setOpen((v) => !v)}
        onKeyDown={(event) => {
          if (event.key === 'ArrowDown' && !open) {
            event.preventDefault()
            setOpen(true)
          }
        }}
      >
        {label}
      </button>
      {open && (
        <ul className="role-menu-list" role="menu" id={menuId} aria-label={t.SETUP.sensorsPickRole} onKeyDown={onKeyDown}>
          {roles.map((role, i) => (
            <li key={role} role="none">
              <button
                ref={(el) => {
                  items.current[i] = el
                }}
                type="button"
                role="menuitem"
                tabIndex={-1}
                onClick={() => {
                  setOpen(false)
                  onPick(role)
                }}
              >
                {t.SETUP.roles[role] ?? role}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function Serial({ d }: { d: SensorEntry }) {
  return d.serial ? (
    <span>
      {t.SETUP.sensorsSerialLabel} {d.serial}
    </span>
  ) : (
    <span>{t.SETUP.sensorsSerialAfter}</span>
  )
}

function AssignedRow({ role, d, send }: { role: string; d: SensorEntry | undefined; send: (c: Command) => void }) {
  const label = t.SETUP.roles[role] ?? role
  if (!d) {
    return (
      <li className="sensor-row assigned vacant" data-testid={`role-${role}`} data-role={role} tabIndex={-1}>
        <div className="sensor-main">
          <b>{label}</b>
          <span className="setup-hint">{t.SETUP.sensorsRoleEmpty}</span>
        </div>
      </li>
    )
  }
  const status = linkStatus(d)
  const muscle = d.kind === 'callibri' && d.link === 'connected'
  const level = Math.min(1, Math.max(0, d.level ?? 0))
  return (
    <li className="sensor-row assigned" data-testid={`role-${role}`} data-role={role} tabIndex={-1}>
      <div className="sensor-main">
        <b>{label}</b>
        <span className="sensor-sub">
          {d.name} · <Serial d={d} />
        </span>
        <span className="sensor-status">
          <span className={`sensor-state ${status.tone}`} aria-live="polite">
            {status.text}
          </span>
          {d.battery !== null && <span className="sensor-battery">{t.SETUP.sensorsBattery(d.battery)}</span>}
        </span>
        {d.error && <span className="sensor-error">{d.error}</span>}
        {muscle && (
          <div className="sensor-level">
            <div
              className="level-bar"
              role="meter"
              aria-label={t.SETUP.sensorsLevelLabel}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.round(level * 100)}
            >
              <span style={{ width: `${Math.round(level * 100)}%` }} />
            </div>
            <span className="setup-hint">{t.SETUP.sensorsLevelHint}</span>
          </div>
        )}
      </div>
      <button type="button" className="setup-action" onClick={() => send({ action: 'sensors_unassign', value: { role } })}>
        {t.SETUP.sensorsDisconnect}
      </button>
    </li>
  )
}

function FoundRow({
  d,
  roles,
  assignedRoles,
  send,
  onAssigned,
}: {
  d: SensorEntry
  roles: string[]
  assignedRoles: Set<string>
  send: (c: Command) => void
  onAssigned: (role: string) => void
}) {
  const fit = roles.filter((r) => t.SETUP.roleKind[r] === d.kind)
  const free = fit.filter((r) => !assignedRoles.has(r))
  const targets = free.length > 0 ? free : fit
  const label = free.length > 0 ? t.SETUP.sensorsConnect : t.SETUP.sensorsReplace
  const assign = (role: string) => {
    send({ action: 'sensors_assign', value: { role, id: d.id } })
    onAssigned(role)
  }
  const needCheck = roles.length === 0
  return (
    <li className={`sensor-row found${d.in_range ? '' : ' stale'}`} data-testid="sensor-found">
      <span className="sensor-kind" title={t.SETUP.sensorsDeviceKind[d.kind] ?? d.kind}>
        <Icon name={d.kind === 'brainbit' ? 'headband' : 'pulse'} />
      </span>
      <div className="sensor-main">
        <b>
          {t.SETUP.sensorsDeviceKind[d.kind] ?? d.kind} <span className="sensor-name">{d.name}</span>
        </b>
        <span className="sensor-sub">
          <Serial d={d} />
        </span>
        {d.link === 'failed' && d.error && <span className="sensor-error">{d.error}</span>}
        <span className="sensor-addr">{d.address}</span>
      </div>
      <div className="sensor-signal">
        {d.in_range ? <RssiBars rssi={d.rssi} /> : <span className="setup-hint">{t.SETUP.sensorsOffline(Math.round(d.age_s))}</span>}
      </div>
      <div className="sensor-action">
        {needCheck ? (
          <button type="button" className="setup-action sensor-connect" disabled title={t.SETUP.sensorsNeedCheck}>
            {t.SETUP.sensorsConnect}
          </button>
        ) : targets.length === 0 ? (
          <span className="setup-hint">{t.SETUP.sensorsNotNeeded}</span>
        ) : targets.length === 1 ? (
          <button
            type="button"
            className="setup-action sensor-connect"
            disabled={!d.in_range}
            onClick={() => assign(targets[0] as string)}
          >
            {label}
          </button>
        ) : (
          <RoleMenu label={label} roles={targets} onPick={assign} disabled={!d.in_range} />
        )}
      </div>
    </li>
  )
}

/** Живой список датчиков: шапка поиска, назначенные по ролям, найденные устройства. */
export function SensorList({
  sensors,
  roles,
  send,
}: {
  sensors: SensorsView | undefined
  roles: string[]
  send: (command: Command) => void
}) {
  const view = sensors ?? IDLE
  const scanning = view.phase === 'scanning'
  const inRange = view.devices.filter((d) => d.in_range).length
  const byRole = new Map(view.devices.filter((d) => d.role !== null).map((d) => [d.role as string, d]))
  const assignedRoles = new Set(byRole.keys())
  const free = view.devices.filter((d) => d.role === null)

  // Строка, на которую нажали «Подключить», исчезает из списка: фокус переходит к строке роли.
  const panel = useRef<HTMLDivElement>(null)
  const [pending, setPending] = useState<string | null>(null)
  useEffect(() => {
    if (pending === null) return
    const row = panel.current?.querySelector<HTMLElement>(`[data-role="${pending}"]`)
    if (row && byRole.has(pending)) {
      ;(row.querySelector<HTMLElement>('button') ?? row).focus()
      setPending(null)
    }
  }, [pending, sensors]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="sensors-panel" ref={panel}>
      <div className="sensors-scan">
        {scanning && <span className="scan-spinner" aria-hidden />}
        <span className="sensors-phase">
          {scanning
            ? t.SETUP.sensorsSearching
            : view.phase === 'idle'
              ? t.SETUP.sensorsIdle
              : view.phase === 'error'
                ? t.SETUP.sensorsFailed
                : t.SETUP.sensorsStopped}
          {view.phase !== 'idle' && view.phase !== 'error' && (
            <>
              {' '}
              <span aria-live="polite" data-testid="sensors-count">
                {t.SETUP.sensorsFound(inRange)}
              </span>
            </>
          )}
          {scanning && <span className="sensors-hint">{t.SETUP.sensorsSearchHint}</span>}
        </span>
        {scanning ? (
          <button type="button" className="setup-action" onClick={() => send({ action: 'sensors_scan_stop' })}>
            {t.SETUP.sensorsStop}
          </button>
        ) : (
          <button type="button" className="setup-action" onClick={() => send({ action: 'sensors_scan_start' })}>
            {view.phase === 'idle' ? t.SETUP.sensorsFind : t.SETUP.sensorsAgain}
          </button>
        )}
      </div>
      {view.phase === 'error' && view.error && <Notice tone="bad">{view.error}</Notice>}

      {roles.length === 0 ? (
        <p className="setup-hint">{t.SETUP.sensorsNeedCheck}</p>
      ) : (
        <section aria-labelledby="sensors-assigned-title">
          <h3 className="sensors-title" id="sensors-assigned-title">
            {t.SETUP.sensorsAssigned}
          </h3>
          <ul className="sensor-rows">
            {roles.map((role) => (
              <AssignedRow key={role} role={role} d={byRole.get(role)} send={send} />
            ))}
          </ul>
        </section>
      )}

      {(free.length > 0 || view.phase === 'scanning' || view.phase === 'stopped') && (
      <section aria-labelledby="sensors-found-title">
        <h3 className="sensors-title" id="sensors-found-title">
          {t.SETUP.sensorsFoundTitle}
        </h3>
        {free.length > 0 ? (
          <ul className="sensor-rows" data-testid="sensors-found">
            {free.map((d) => (
              <FoundRow key={d.id} d={d} roles={roles} assignedRoles={assignedRoles} send={send} onAssigned={setPending} />
            ))}
          </ul>
        ) : view.phase === 'stopped' ? (
          <Notice tone="warn" testId="sensors-none">
            <b>{t.SETUP.sensorsNone}</b>
            <ul>
              {t.SETUP.sensorsNoneTips.map((tip) => (
                <li key={tip}>{tip}</li>
              ))}
            </ul>
          </Notice>
        ) : scanning ? (
          <p className="setup-hint">{t.SETUP.sensorsWaiting}</p>
        ) : null}
      </section>
      )}
    </div>
  )
}
