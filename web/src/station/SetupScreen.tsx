import { motion } from 'motion/react'
import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { cameraConstraints, listCameras } from './camera.ts'
import type { CameraInfo } from './camera.ts'
import { Icon } from './Icon.tsx'
import { BreakablePath, Notice } from './Notice.tsx'
import { Select } from './Select.tsx'
import { SensorsSection } from './SensorsSection.tsx'
import * as t from './texts.ts'
import type { Command, SetupFields, StateView } from './types.ts'

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

  const none = cameras !== null && cameras.length === 0
  const missing = value !== '' && cameras !== null && !cameras.some((c) => c.label === value)
  const options = [
    { value: '', label: none ? t.SETUP.cameraNone : t.SETUP.cameraDefault },
    ...(cameras ?? []).map((camera) => ({ value: camera.label, label: camera.label })),
  ]
  return (
    <div className="setup-field">
      <span className="setup-label" id="setup-camera-label">
        {t.SETUP.camera}
      </span>
      <div className="setup-camera">
        <video ref={video} muted playsInline className="setup-preview" />
        <div className="setup-camera-side">
          <Select
            labelId="setup-camera-label"
            value={missing ? '' : value}
            options={options}
            onChange={onChange}
            disabled={none}
          />
          {missing && <span className="setup-hint warn">{t.SETUP.cameraMissing}</span>}
        </div>
      </div>
    </div>
  )
}

/** Первая настройка: адрес сервера, токен станции, игра. Дисциплину сообщает сервер. */
export function SetupScreen({
  state,
  send,
  commandError = null,
}: {
  state: SetupState
  send: (command: Command) => void
  /** Текст отказа ядра на последнюю команду (например, «подключить» до ввода токена). */
  commandError?: string | null
}) {
  const [fields, setFields] = useState<SetupFields>(() => {
    const { devices: _legacy, ...form } = state.form
    return { ...form, token: '' }
  })
  const [showToken, setShowToken] = useState(false)
  // Сохранить можно только проверенное: правка поля после проверки сбрасывает «готово».
  const [checked, setChecked] = useState<SetupFields | null>(null)
  const busy = state.phase === 'checking' || state.phase === 'saved'
  const ready = state.phase === 'ok' && checked !== null && same(checked, fields)
  const actions = useRef<HTMLDivElement>(null)
  // Результат проверки появляется под длинной формой: прокручиваем к нему вместе с кнопками.
  useEffect(() => {
    if (state.phase === 'ok' || state.error) actions.current?.scrollIntoView?.({ block: 'end', behavior: 'smooth' })
  }, [state.phase, state.error])
  // Токен, адрес или сертификат изменились: ядро само (с задержкой) проверит токен и узнает роли.
  const formKey = `${fields.server_url}
${fields.token}
${fields.ca_file}`
  const lastForm = useRef(formKey)
  const latest = useRef({ fields, send })
  useEffect(() => {
    latest.current = { fields, send }
  })
  useEffect(() => {
    if (lastForm.current === formKey) return
    lastForm.current = formKey
    latest.current.send({ action: 'setup_form', value: latest.current.fields })
  }, [formKey])
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
          hint={state.games_bundled ? t.SETUP.gameAutoHint : undefined}
          value={fields.game_path}
          placeholder={state.games_bundled ? t.SETUP.gameAuto : t.SETUP.gameHint}
          onChange={set('game_path')}
          action={pick('game', 'game_path')}
        />
        <CameraPicker value={fields.camera} onChange={set('camera')} />
        <SensorsSection
          state={state}
          fields={fields}
          setFields={setFields}
          send={send}
          notice={commandError}
        />
        <Field
          label={t.SETUP.cert}
          hint={t.SETUP.certHint}
          value={fields.ca_file}
          placeholder=""
          onChange={set('ca_file')}
          action={pick('cert', 'ca_file')}
        />

        <div className="setup-result" aria-live="polite">
          {state.phase === 'checking' && (
            <div className="notice notice-info">
              <span className="scan-spinner" aria-hidden />
              <div className="notice-text">{t.SETUP.checking}</div>
            </div>
          )}
          {state.phase === 'saved' && <Notice tone="good">{t.SETUP.saved}</Notice>}
          {state.error && (
            <motion.div key={state.error} initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }}>
              <Notice tone="bad">{state.error}</Notice>
            </motion.div>
          )}
          {ready && state.discipline && (
            <motion.div initial={{ opacity: 0, scale: 0.98 }} animate={{ opacity: 1, scale: 1 }}>
              <Notice tone="good" testId="setup-ok">
                <b>
                  {t.SETUP.connected} «{t.DISCIPLINE_NAMES[state.discipline] ?? state.discipline}»
                </b>
                <div>{state.players_needed === 2 ? t.SETUP.playersTwo : t.SETUP.playersOne}</div>
                {state.game && (
                  <div className="notice-sub" data-testid="setup-game">
                    {t.SETUP.gameWillRun}: <BreakablePath path={state.game} />
                  </div>
                )}
              </Notice>
            </motion.div>
          )}
        </div>

        <div className="setup-actions" ref={actions}>
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
    a.sensors === b.sensors
  )
}
