import { motion } from 'motion/react'
import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { cameraConstraints, listCameras } from './camera.ts'
import type { CameraInfo } from './camera.ts'
import { Chip } from './Frame.tsx'
import { Icon } from './Icon.tsx'
import * as t from './texts.ts'
import type { Command, SensorDevice, SetupFields, StateView } from './types.ts'

type SetupState = Extract<StateView, { kind: 'setup' }>

declare global {
  interface Window {
    /** Диалоги выбора файла: даёт окно Electron (preload). */
    stationShell?: { pickFile: (kind: 'game' | 'cert') => Promise<string | null> }
  }
}

interface FieldProps {
  label: string
  hint?: string
  value: string
  placeholder: string
  onChange: (value: string) => void
  type?: 'text' | 'password'
  action?: { label: string; onClick: () => void } | undefined
  autoFocus?: boolean
}

function Field({ label, hint, value, placeholder, onChange, type = 'text', action, autoFocus }: FieldProps) {
  return (
    <label className="setup-field">
      <span className="setup-label">{label}</span>
      <span className="setup-input">
        <input
          type={type}
          value={value}
          placeholder={placeholder}
          autoFocus={autoFocus}
          spellCheck={false}
          autoComplete="off"
          onChange={(event) => onChange(event.target.value)}
        />
        {action && (
          <button type="button" className="setup-action" onClick={action.onClick}>
            {action.label}
          </button>
        )}
      </span>
      {hint && <span className="setup-hint">{hint}</span>}
    </label>
  )
}

/** Выбор камеры для QR: список подключённых и живое превью выбранной. */
function CameraPicker({ value, onChange }: { value: string; onChange: (label: string) => void }) {
  const [cameras, setCameras] = useState<CameraInfo[] | null>(null)
  const video = useRef<HTMLVideoElement>(null)

  useEffect(() => {
    let alive = true
    const refresh = () => void listCameras().then((list) => alive && setCameras(list))
    refresh()
    navigator.mediaDevices?.addEventListener?.('devicechange', refresh)
    return () => {
      alive = false
      navigator.mediaDevices?.removeEventListener?.('devicechange', refresh)
    }
  }, [])

  useEffect(() => {
    let stream: MediaStream | null = null
    let alive = true
    const element = video.current
    if (typeof navigator.mediaDevices?.getUserMedia !== 'function' || !element) return
    cameraConstraints(value || null)
      .then((constraints) => navigator.mediaDevices.getUserMedia(constraints))
      .then((media) => {
        if (!alive) return media.getTracks().forEach((track) => track.stop())
        stream = media
        element.srcObject = media
        void element.play()
      })
      .catch(() => undefined)
    return () => {
      alive = false
      stream?.getTracks().forEach((track) => track.stop())
    }
  }, [value])

  const missing = value !== '' && cameras !== null && !cameras.some((c) => c.label === value)
  return (
    <div className="setup-field">
      <label className="setup-label" htmlFor="setup-camera">
        {t.SETUP.camera}
      </label>
      <div className="setup-camera">
        <video ref={video} muted playsInline className="setup-preview" />
        <div className="setup-camera-side">
          <select
            id="setup-camera"
            value={missing ? '' : value}
            onChange={(event) => onChange(event.target.value)}
            disabled={cameras !== null && cameras.length === 0}
          >
            <option value="">
              {cameras !== null && cameras.length === 0 ? t.SETUP.cameraNone : t.SETUP.cameraDefault}
            </option>
            {(cameras ?? []).map((camera) => (
              <option key={camera.id} value={camera.label}>
                {camera.label}
              </option>
            ))}
          </select>
          {missing && <span className="setup-hint warn">{t.SETUP.cameraMissing}</span>}
        </div>
      </div>
    </div>
  )
}

/** Раздел «Датчики»: режим, поиск и серийные номера по ролям дисциплины. */
function SensorsSection({
  state,
  fields,
  setFields,
  send,
}: {
  state: SetupState
  fields: SetupFields
  setFields: (update: (fields: SetupFields) => SetupFields) => void
  send: (command: Command) => void
}) {
  if (!state.sensors_available) return null
  const scan = state.scan
  const hardware = fields.sensors === 'hardware'
  const setSerial = (role: string, serial: string) =>
    setFields((f) => ({ ...f, devices: { ...f.devices, [role]: serial } }))
  const offered = (role: string): SensorDevice[] =>
    scan.devices.filter((d) => d.kind === t.SETUP.roleKind[role] && d.serial !== '')
  return (
    <div className="setup-field setup-sensors">
      <label className="setup-label" htmlFor="setup-sensors">
        {t.SETUP.sensors}
      </label>
      <select
        id="setup-sensors"
        value={fields.sensors}
        onChange={(event) => setFields((f) => ({ ...f, sensors: event.target.value }))}
      >
        <option value="hardware">{t.SETUP.sensorsHardware}</option>
        <option value="emulate">{t.SETUP.sensorsEmulate}</option>
        <option value="">{t.SETUP.sensorsExternal}</option>
      </select>
      {hardware && (
        <div className="sensors-panel">
          <div className="sensors-scan">
            <button
              type="button"
              className="setup-action"
              disabled={scan.phase === 'scanning'}
              onClick={() => send({ action: 'sensors_scan' })}
            >
              {t.SETUP.sensorsScan}
            </button>
            {scan.phase === 'scanning' && <span className="setup-hint">{t.SETUP.sensorsScanning}</span>}
            {scan.phase === 'done' && scan.error && <span className="setup-hint warn">{scan.error}</span>}
            {scan.phase === 'done' && !scan.error && scan.devices.length === 0 && (
              <span className="setup-hint warn">{t.SETUP.sensorsNone}</span>
            )}
          </div>
          {scan.devices.length > 0 && (
            <ul className="sensors-found" data-testid="sensors-found">
              {scan.devices.map((d) => (
                <li key={d.address}>
                  <b>{t.SETUP.sensorsDeviceKind[d.kind] ?? d.kind}</b> {d.name}{' '}
                  <span className="setup-hint">
                    {d.serial || t.SETUP.sensorsSerialUnknown} · {d.address}
                  </span>
                </li>
              ))}
            </ul>
          )}
          {state.roles.length === 0 ? (
            <p className="setup-hint">{t.SETUP.sensorsNeedCheck}</p>
          ) : (
            state.roles.map((role) => (
              <label key={role} className="sensors-role">
                <span>{t.SETUP.roles[role] ?? role}</span>
                <input
                  value={fields.devices[role] ?? ''}
                  placeholder={t.SETUP.sensorsSerial}
                  list={`serials-${role}`}
                  spellCheck={false}
                  autoComplete="off"
                  onChange={(event) => setSerial(role, event.target.value)}
                />
                <datalist id={`serials-${role}`}>
                  {offered(role).map((d) => (
                    <option key={d.address} value={d.serial} label={d.name} />
                  ))}
                </datalist>
              </label>
            ))
          )}
        </div>
      )}
    </div>
  )
}

/** Первая настройка: адрес сервера, токен станции, игра. Дисциплину сообщает сервер. */
export function SetupScreen({
  state,
  send,
}: {
  state: SetupState
  send: (command: Command) => void
}) {
  const [fields, setFields] = useState<SetupFields>({
    ...state.form,
    devices: { ...state.form.devices },
    token: '',
  })
  const [showToken, setShowToken] = useState(false)
  // Сохранить можно только проверенное: правка поля после проверки сбрасывает «готово».
  const [checked, setChecked] = useState<SetupFields | null>(null)
  const busy = state.phase === 'checking' || state.phase === 'saved'
  const ready = state.phase === 'ok' && checked !== null && same(checked, fields)
  const set = (key: keyof SetupFields) => (value: string) => setFields((f) => ({ ...f, [key]: value }))

  const pick = (kind: 'game' | 'cert', key: 'game_path' | 'ca_file') => {
    const shell = window.stationShell
    return shell
      ? { label: t.SETUP.browse, onClick: () => void shell.pickFile(kind).then((path) => path && set(key)(path)) }
      : undefined
  }

  const check = (event?: FormEvent) => {
    event?.preventDefault()
    if (busy) return
    setChecked(fields)
    send({ action: 'setup_check', value: fields })
  }

  return (
    <form className="setup" onSubmit={check} data-phase={state.phase}>
      <div className="setup-card card">
        <h1 className="setup-title">{t.SETUP.title}</h1>
        <p className="setup-lead">{t.SETUP.lead}</p>

        <Field
          label={t.SETUP.server}
          value={fields.server_url}
          placeholder={t.SETUP.serverHint}
          onChange={set('server_url')}
          autoFocus
        />
        <Field
          label={t.SETUP.token}
          hint={state.has_token ? t.SETUP.tokenSaved : t.SETUP.tokenHint}
          value={fields.token}
          placeholder={state.has_token ? '••••••••••••' : ''}
          type={showToken ? 'text' : 'password'}
          onChange={set('token')}
          action={{ label: showToken ? t.SETUP.hide : t.SETUP.show, onClick: () => setShowToken((v) => !v) }}
        />
        <Field
          label={t.SETUP.game}
          value={fields.game_path}
          placeholder={t.SETUP.gameHint}
          onChange={set('game_path')}
          action={pick('game', 'game_path')}
        />
        <CameraPicker value={fields.camera} onChange={set('camera')} />
        <SensorsSection state={state} fields={fields} setFields={setFields} send={send} />
        <Field
          label={t.SETUP.cert}
          hint={t.SETUP.certHint}
          value={fields.ca_file}
          placeholder=""
          onChange={set('ca_file')}
          action={pick('cert', 'ca_file')}
        />

        <div className="setup-result" aria-live="polite">
          {state.phase === 'checking' && <Chip tone="muted">{t.SETUP.checking}</Chip>}
          {state.phase === 'saved' && (
            <Chip tone="good" icon="check">
              {t.SETUP.saved}
            </Chip>
          )}
          {state.error && (
            <motion.div key={state.error} initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }}>
              <Chip tone="bad" icon="warning">
                {state.error}
              </Chip>
            </motion.div>
          )}
          {ready && state.discipline && (
            <motion.div
              className="setup-ok"
              initial={{ opacity: 0, scale: 0.96 }}
              animate={{ opacity: 1, scale: 1 }}
              data-testid="setup-ok"
            >
              <Icon name="check" />
              <span>
                {t.SETUP.connected} «{t.DISCIPLINE_NAMES[state.discipline] ?? state.discipline}»,{' '}
                {state.players_needed === 2 ? t.SETUP.playersTwo : t.SETUP.playersOne}
              </span>
            </motion.div>
          )}
        </div>

        <div className="setup-actions">
          <button type="submit" className="ghost wide setup-check" disabled={busy}>
            {t.SETUP.check}
          </button>
          <button
            type="button"
            className="play setup-save"
            disabled={!ready || busy}
            onClick={() => send({ action: 'setup_save', value: fields })}
          >
            <Icon name="play" />
            {t.SETUP.save}
          </button>
        </div>
      </div>
    </form>
  )
}

function same(a: SetupFields, b: SetupFields): boolean {
  return (
    a.server_url === b.server_url &&
    a.token === b.token &&
    a.game_path === b.game_path &&
    a.ca_file === b.ca_file &&
    a.camera === b.camera &&
    a.sensors === b.sensors &&
    JSON.stringify(a.devices) === JSON.stringify(b.devices)
  )
}
