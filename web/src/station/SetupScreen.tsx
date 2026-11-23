import { motion } from 'motion/react'
import { useState } from 'react'
import type { FormEvent } from 'react'
import { Chip } from './Frame.tsx'
import { Icon } from './Icon.tsx'
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

/** Первая настройка: адрес сервера, токен станции, игра. Дисциплину сообщает сервер. */
export function SetupScreen({
  state,
  send,
}: {
  state: SetupState
  send: (command: Command) => void
}) {
  const [fields, setFields] = useState<SetupFields>({ ...state.form, token: '' })
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
    a.ca_file === b.ca_file
  )
}
