import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { DISCIPLINE_NAMES } from '../../shared/messages.ts'
import { DisciplineIcon } from '../../shared/icons/DisciplineIcon.tsx'
import { DISCIPLINES } from '../../shared/types.ts'
import type { Discipline } from '../../shared/types.ts'
import type { StaffApi, StationInfo, StationWithToken } from '../api.ts'
import { ConfirmDialog, ErrorText } from '../ui.tsx'
import { useAction, useLoader } from '../hooks.ts'
import { ONLINE_HINT, QUEUE_HINT, lastSeen, onlineAgo, stateName } from './stationStatus.ts'
import './StationsTab.css'

export const STATIONS_REFRESH_MS = 5000
const CLOCK_TICK_MS = 5000

/** Текущее время браузера: обновляется само, данные списка при этом не перезагружаются. */
function useNow(): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), CLOCK_TICK_MS)
    return () => clearInterval(timer)
  }, [])
  return now
}

export function StationsTab({ api }: { api: StaffApi }) {
  const list = useLoader(() => api.stations(), STATIONS_REFRESH_MS)
  const creation = useAction()
  const rotation = useAction()
  const removal = useAction()
  const now = useNow()
  const [name, setName] = useState('')
  const [discipline, setDiscipline] = useState<Discipline>('darts')
  const [issued, setIssued] = useState<StationWithToken | null>(null)
  const [rotating, setRotating] = useState<number | null>(null)
  const [deleting, setDeleting] = useState<number | null>(null)

  async function create(event: FormEvent) {
    event.preventDefault()
    const station = await creation.run(() => api.createStation(name.trim(), discipline))
    if (station) {
      setIssued(station)
      setName('')
      list.reload()
    }
  }

  async function rotate(id: number) {
    const station = await rotation.run(() => api.rotateStationToken(id))
    if (station) {
      setRotating(null)
      setIssued(station)
    }
  }

  async function remove(id: number) {
    const done = await removal.run(async () => {
      await api.deleteStation(id)
      return true
    })
    if (done) {
      setDeleting(null)
      setIssued((current) => (current?.id === id ? null : current))
      list.reload()
    }
  }

  function cancelRotate() {
    rotation.clear()
    setRotating(null)
  }

  function cancelDelete() {
    removal.clear()
    setDeleting(null)
  }

  const stations = list.data ?? []
  const rotatingStation = stations.find((s) => s.id === rotating)
  const deletingStation = stations.find((s) => s.id === deleting)
  return (
    <section className="stack stations">
      <form className="card stations-form" onSubmit={(e) => void create(e)}>
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
        <button type="submit" className="primary" disabled={creation.busy || name.trim() === ''}>
          Создать станцию
        </button>
      </form>
      <ErrorText error={creation.error ?? list.error} />

      {issued && <TokenPanel station={issued} onDone={() => setIssued(null)} />}

      <p className="stations-hint">{ONLINE_HINT}</p>
      <div className="stations-grid">
        {stations.map((station) => (
          <StationCard
            key={station.id}
            station={station}
            now={now}
            onRotate={() => setRotating(station.id)}
            onDelete={() => setDeleting(station.id)}
          />
        ))}
      </div>

      {rotatingStation && (
        <ConfirmDialog
          title="Выдать новый токен?"
          message={
            <>
              <p>{`Старый токен станции «${rotatingStation.name}» перестанет работать. Лаунчер придётся перенастроить.`}</p>
              <ErrorText error={rotation.error} />
            </>
          }
          confirmLabel="Выдать новый токен"
          busy={rotation.busy}
          onConfirm={() => void rotate(rotatingStation.id)}
          onCancel={cancelRotate}
        />
      )}
      {deletingStation && (
        <ConfirmDialog
          title="Удалить станцию?"
          message={
            <>
              <p>
                {`Станция «${deletingStation.name}» исчезнет из списка, её токен перестанет работать. История в журнале сохранится. Это действие нельзя отменить.`}
              </p>
              <ErrorText error={removal.error} />
            </>
          }
          confirmLabel="Удалить станцию"
          busy={removal.busy}
          onConfirm={() => void remove(deletingStation.id)}
          onCancel={cancelDelete}
        />
      )}
    </section>
  )
}

function StationCard({
  station,
  now,
  onRotate,
  onDelete,
}: {
  station: StationInfo
  now: number
  onRotate: () => void
  onDelete: () => void
}) {
  const ago = station.online ? onlineAgo(station.last_heartbeat_at, now) : null
  return (
    <div className="station-card" role="group" aria-label={station.name}>
      <div className="station-head">
        <span className="station-icon">
          <DisciplineIcon discipline={station.discipline} />
        </span>
        <div className="station-title">
          <strong>{station.name}</strong>
          <span className="station-discipline">{DISCIPLINE_NAMES[station.discipline]}</span>
        </div>
        <span className={station.online ? 'station-status online' : 'station-status offline'}>
          <span className="station-dot" aria-hidden="true" />
          {station.online ? 'В сети' : 'Не в сети'}
        </span>
      </div>
      <div className="station-body">
        {station.online ? (
          <>
            {ago && <span className="station-note">{ago}</span>}
            {station.last_state && <span>{stateName(station.last_state)}</span>}
          </>
        ) : (
          <span className="station-note">{lastSeen(station.last_heartbeat_at, now)}</span>
        )}
        {station.queue_length > 0 && (
          <span className="station-queue" title={QUEUE_HINT}>
            ждут отправки: {station.queue_length}
          </span>
        )}
      </div>
      <div className="station-actions">
        <button
          type="button"
          className="small"
          aria-label={`Новый токен ${station.name}`}
          onClick={onRotate}
        >
          Новый токен
        </button>
        <button
          type="button"
          className="small danger"
          aria-label={`Удалить станцию ${station.name}`}
          onClick={onDelete}
        >
          Удалить станцию
        </button>
      </div>
    </div>
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
