import { useState } from 'react'
import { DisciplineIcon } from '../../shared/icons/DisciplineIcon.tsx'
import { DISCIPLINE_NAMES } from '../../shared/messages.ts'
import type { DisciplineSettings, StaffApi } from '../api.ts'
import { ErrorText } from '../ui.tsx'
import { useAction, useLoader } from '../hooks.ts'

type Field = 'game_duration_s' | 'physical_duration_s' | 'win_points' | 'max_section_points'

interface FieldSpec {
  id: Field
  /** Короткая подпись над полем; она же входит в доступное имя вместе с единицей и дисциплиной. */
  label: string
  unit: string
  min: number
  max: number
}

const FIELDS: FieldSpec[] = [
  { id: 'game_duration_s', label: 'Игра', unit: 'с', min: 10, max: 3600 },
  { id: 'physical_duration_s', label: 'Физ. секция', unit: 'с', min: 10, max: 3600 },
  { id: 'win_points', label: 'За победу', unit: 'очк.', min: 0, max: 1000 },
  { id: 'max_section_points', label: 'Лимит секции', unit: 'очк.', min: 1, max: 1000 },
]

export function DisciplinesTab({ api }: { api: StaffApi }) {
  const list = useLoader(() => api.disciplines())
  return (
    <section className="stack">
      <p className="hint">
        Лимит очков за секцию действует для дартса и футбола (физика и BCI); понг считается по победам.
        Новое время применяется со следующей сессии, идущая не обрывается. Изменение пишется в журнал.
      </p>
      <ErrorText error={list.error} />
      <div className="discipline-grid">
        {(list.data ?? []).map((discipline) => (
          <DisciplineCard key={discipline.code} api={api} discipline={discipline} onSaved={list.reload} />
        ))}
      </div>
    </section>
  )
}

interface CardProps {
  api: StaffApi
  discipline: DisciplineSettings
  onSaved: () => void
}

function DisciplineCard({ api, discipline, onSaved }: CardProps) {
  const action = useAction()
  const [values, setValues] = useState<Record<Field, string>>({
    game_duration_s: String(discipline.game_duration_s),
    physical_duration_s: String(discipline.physical_duration_s),
    win_points: String(discipline.win_points),
    max_section_points: String(discipline.max_section_points),
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
    <div className="card discipline-card" role="group" aria-label={name}>
      <h2 className="discipline-head">
        <span className="discipline-icon">
          <DisciplineIcon discipline={discipline.code} />
        </span>
        {name}
      </h2>
      <div className="discipline-fields">
        {FIELDS.map((field) => (
          <label key={field.id} className="field">
            {field.label}
            <span className="with-unit">
              <input
                type="number"
                min={field.min}
                max={field.max}
                aria-label={`${field.label}, ${field.unit} (${name})`}
                value={values[field.id]}
                onChange={(e) => {
                  setSaved(false)
                  setValues({ ...values, [field.id]: e.target.value })
                }}
              />
              <span className="unit" aria-hidden>
                {field.unit}
              </span>
            </span>
            {field.id === 'max_section_points' && (
              <small className="field-hint">
                {discipline.code === 'pong' ? 'Понг лимитом не ограничен' : 'Максимум за физику и BCI'}
              </small>
            )}
          </label>
        ))}
      </div>
      {!valid && <p className="error">Проверьте значения: целые числа в допустимых пределах</p>}
      <ErrorText error={action.error} />
      <div className="discipline-actions">
        <button
          type="button"
          className="primary"
          aria-label={`Сохранить ${name}`}
          disabled={!dirty || !valid || action.busy}
          onClick={() => void save()}
        >
          Сохранить
        </button>
        {saved && !dirty && <span role="status">Сохранено</span>}
      </div>
    </div>
  )
}
