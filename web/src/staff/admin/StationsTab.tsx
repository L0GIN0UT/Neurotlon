import { useState } from 'react'
import type { FormEvent } from 'react'
import { DISCIPLINE_NAMES } from '../../shared/messages.ts'
import { DISCIPLINES } from '../../shared/types.ts'
import type { Discipline } from '../../shared/types.ts'
import type { StaffApi, StationWithToken } from '../api.ts'
import { ConfirmDialog, ErrorText } from '../ui.tsx'
import { formatTime } from '../format.ts'
import { useAction, useLoader } from '../hooks.ts'

export const STATIONS_REFRESH_MS = 5000

const STATE_NAMES: Record<string, string> = {
  idle: 'ждёт',
  confirming: 'подтверждение',
  calibrating: 'калибровка',
  playing: 'игра',
  sending: 'отправка',
}

export function StationsTab({ api }: { api: StaffApi }) {
  const list = useLoader(() => api.stations(), STATIONS_REFRESH_MS)
  const action = useAction()
  const [name, setName] = useState('')
  const [discipline, setDiscipline] = useState<Discipline>('darts')
  const [issued, setIssued] = useState<StationWithToken | null>(null)
  const [rotating, setRotating] = useState<number | null>(null)

  async function create(event: FormEvent) {
    event.preventDefault()
    const station = await action.run(() => api.createStation(name.trim(), discipline))
    if (station) {
      setIssued(station)
      setName('')
      list.reload()
    }
  }

  async function rotate(id: number) {
    const station = await action.run(() => api.rotateStationToken(id))
    setRotating(null)
    if (station) setIssued(station)
  }

  const rotatingStation = list.data?.find((s) => s.id === rotating)
  return (
    <section className="stack">
      <form className="row card" onSubmit={(e) => void create(e)}>
        <label className="field">
          Название станции
          <input value={name} maxLength={64} onChange={(e) => setName(e.target.value)} required />
        </label>
        <label className="field">
          Дисциплина
          <select
            value={discipline}
            onChange={(e) => setDiscipline(e.target.value as Discipline)}
          >
            {DISCIPLINES.map((code) => (
              <option key={code} value={code}>
                {DISCIPLINE_NAMES[code]}
              </option>
            ))}
          </select>
        </label>
        <button type="submit" className="primary" disabled={action.busy || name.trim() === ''}>
          Создать станцию
        </button>
      </form>
      <ErrorText error={action.error ?? list.error} />

      {issued && <TokenPanel station={issued} onDone={() => setIssued(null)} />}

      <table className="card">
        <thead>
          <tr>
            <th>Станция</th>
            <th>Дисциплина</th>
            <th>Связь</th>
            <th>Последний сигнал</th>
            <th>Состояние</th>
            <th>В очереди</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {(list.data ?? []).map((station) => (
            <tr key={station.id}>
              <td>{station.name}</td>
              <td>{DISCIPLINE_NAMES[station.discipline]}</td>
              <td>
                <span className={station.online ? 'badge ok' : 'badge bad'}>
                  {station.online ? 'на связи' : 'нет связи'}
                </span>
              </td>
              <td>{formatTime(station.last_heartbeat_at)}</td>
              <td>{station.last_state ? (STATE_NAMES[station.last_state] ?? station.last_state) : '—'}</td>
              <td>{station.queue_length}</td>
              <td className="actions">
                <button
                  type="button"
                  className="small"
                  aria-label={`Новый токен ${station.name}`}
                  onClick={() => setRotating(station.id)}
                >
                  Новый токен
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {rotatingStation && (
        <ConfirmDialog
          title="Выдать новый токен?"
          message={`Старый токен станции «${rotatingStation.name}» перестанет работать. Лаунчер придётся перенастроить.`}
          confirmLabel="Выдать новый токен"
          busy={action.busy}
          onConfirm={() => void rotate(rotatingStation.id)}
          onCancel={() => setRotating(null)}
        />
      )}
    </section>
  )
}

function TokenPanel({ station, onDone }: { station: StationWithToken; onDone: () => void }) {
  const [copied, setCopied] = useState<'yes' | 'no' | null>(null)

  async function copy() {
    try {
      await navigator.clipboard.writeText(station.token)
      setCopied('yes')
    } catch {
      setCopied('no') // без HTTPS буфер недоступен: токен можно выделить вручную
    }
  }

  return (
    <div className="card stack token-panel" role="region" aria-label="Токен станции">
      <h2>Токен станции «{station.name}»</h2>
      <p className="warning">
        Токен показан один раз. Скопируйте его в настройки лаунчера сейчас: позже его не увидеть,
        можно только выдать новый.
      </p>
      <code className="token">{station.token}</code>
      <div className="row">
        <button type="button" className="primary" onClick={() => void copy()}>
          Скопировать токен
        </button>
        <button type="button" onClick={onDone}>
          Я сохранил токен
        </button>
      </div>
      {copied === 'yes' && <p role="status">Скопировано</p>}
      {copied === 'no' && <p className="error">Не удалось скопировать: выделите токен вручную.</p>}
    </div>
  )
}
