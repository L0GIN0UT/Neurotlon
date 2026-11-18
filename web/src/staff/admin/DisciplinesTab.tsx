import { useState } from 'react'
import { DISCIPLINE_NAMES } from '../../shared/messages.ts'
import type { DisciplineSettings, StaffApi } from '../api.ts'
import { ErrorText } from '../ui.tsx'
import { useAction, useLoader } from '../hooks.ts'

type Field = 'game_duration_s' | 'physical_duration_s' | 'win_points'

const FIELDS: { id: Field; label: string; min: number; max: number }[] = [
  { id: 'game_duration_s', label: 'Время игры, с', min: 10, max: 3600 },
  { id: 'physical_duration_s', label: 'Время физической секции, с', min: 10, max: 3600 },
  { id: 'win_points', label: 'Очки за победу', min: 0, max: 1000 },
]

export function DisciplinesTab({ api }: { api: StaffApi }) {
  const list = useLoader(() => api.disciplines())
  return (
    <section className="stack">
      <p>
        Новое время применяется со следующей сессии, идущая не обрывается. Изменение пишется в журнал.
      </p>
      <ErrorText error={list.error} />
      {(list.data ?? []).map((discipline) => (
        <DisciplineRow key={discipline.code} api={api} discipline={discipline} onSaved={list.reload} />
      ))}
    </section>
  )
}

interface RowProps {
  api: StaffApi
  discipline: DisciplineSettings
  onSaved: () => void
}

function DisciplineRow({ api, discipline, onSaved }: RowProps) {
  const action = useAction()
  const [values, setValues] = useState<Record<Field, string>>({
    game_duration_s: String(discipline.game_duration_s),
    physical_duration_s: String(discipline.physical_duration_s),
    win_points: String(discipline.win_points),
  })
  const [saved, setSaved] = useState(false)
  const name = DISCIPLINE_NAMES[discipline.code]

  const changes: Partial<Record<Field, number>> = {}
  let valid = true
  for (const field of FIELDS) {
    const value = Number(values[field.id])
    if (!Number.isInteger(value) || value < field.min || value > field.max) valid = false
    else if (value !== discipline[field.id]) changes[field.id] = value
  }
  const dirty = Object.keys(changes).length > 0

  async function save() {
    setSaved(false)
    if (await action.run(() => api.patchDiscipline(discipline.code, changes))) {
      setSaved(true)
      onSaved()
    }
  }

  return (
    <div className="card row" role="group" aria-label={name}>
      <h2 className="grow">{name}</h2>
      {FIELDS.map((field) => (
        <label key={field.id} className="field">
          {field.label} ({name})
          <input
            type="number"
            min={field.min}
            max={field.max}
            value={values[field.id]}
            onChange={(e) => {
              setSaved(false)
              setValues({ ...values, [field.id]: e.target.value })
            }}
          />
        </label>
      ))}
      <button type="button" className="primary" disabled={!dirty || !valid || action.busy} onClick={() => void save()}>
        Сохранить {name}
      </button>
      {!valid && <p className="error">Проверьте значения: целые числа в допустимых пределах</p>}
      {saved && !dirty && <p role="status">Сохранено</p>}
      <ErrorText error={action.error} />
    </div>
  )
}
