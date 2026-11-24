import { useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import { DISCIPLINE_NAMES } from '../../shared/messages.ts'
import { DISCIPLINES } from '../../shared/types.ts'
import type { Category, DisciplineSettings, Participant, StaffApi, StoredResult } from '../api.ts'
import { BADGES_URL } from '../api.ts'
import { formatTime } from '../format.ts'
import { useAction, useLoader } from '../hooks.ts'
import { indexResults, scoreCell, SECTIONS } from '../scores.ts'
import { Dialog, ErrorText } from '../ui.tsx'

const MAX_NAME = 24

/** Подписи форм в столбцах: BCI и «реальная» оценка. */
const SECTION_HEAD = { bci: 'BCI', physical: 'Реальная' } as const

type Editing =
  | { kind: 'check-in'; person: Participant }
  | { kind: 'rename'; person: Participant }

type Filter = 'all' | 'here' | 'absent'

const FILTERS: { id: Filter; label: string }[] = [
  { id: 'all', label: 'Все' },
  { id: 'here', label: 'Пришли' },
  { id: 'absent', label: 'Не пришли' },
]

const NO_RESULTS: StoredResult[] = []
const NO_SETTINGS: DisciplineSettings[] = []

export function ParticipantsTab({ api }: { api: StaffApi }) {
  const list = useLoader(() => api.participants())
  // Баллы и лимиты нужны только для столбцов с очками: сбой их загрузки не мешает работе со списком.
  const results = useLoader(() => api.allResults().catch(() => NO_RESULTS), 15000)
  const settings = useLoader(() => api.disciplines().catch(() => NO_SETTINGS))
  const action = useAction()
  const [count, setCount] = useState('20')
  const [editing, setEditing] = useState<Editing | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState<Filter>('all')

  async function generate(event: FormEvent) {
    event.preventDefault()
    const result = await action.run(() => api.generateParticipants(Number(count)))
    if (result) {
      setNotice(
        result.created.length > 0
          ? `Создано: ${result.created.length}, всего ${result.total}`
          : `Новых ID нет, всего ${result.total}`,
      )
      list.reload()
    }
  }

  async function undo(person: Participant) {
    if (await action.run(() => api.undoCheckIn(person.code))) list.reload()
  }

  const everyone = list.data ?? []
  const index = useMemo(() => indexResults(results.data ?? NO_RESULTS), [results.data])
  const limits = Object.fromEntries(
    (settings.data ?? NO_SETTINGS).map((d) => [d.code, d.max_section_points]),
  )
  const needle = search.trim().toLowerCase()
  const people = everyone.filter(
    (person) =>
      (filter === 'all' || (filter === 'here') === person.checked_in) &&
      (needle === '' ||
        person.code.toLowerCase().includes(needle) ||
        (person.display_name ?? '').toLowerCase().includes(needle)),
  )
  const arrived = everyone.filter((person) => person.checked_in).length
  return (
    <section className="stack">
      <div className="row card no-print">
        <form className="row" onSubmit={(e) => void generate(e)}>
          <label className="field">
            Сколько ID создать
            <input
              type="number"
              min={1}
              max={99}
              value={count}
              onChange={(e) => setCount(e.target.value)}
            />
          </label>
          <button type="submit" className="primary" disabled={action.busy}>
            Создать ID
          </button>
        </form>
        <button
          type="button"
          disabled={everyone.length === 0}
          onClick={() => window.open(BADGES_URL, '_blank')}
        >
          Печать бейджей
        </button>
        {notice && <span role="status">{notice}</span>}
      </div>
      <ErrorText error={action.error ?? list.error} />

      <div className="row no-print">
        <label className="field grow">
          Поиск
          <input
            type="search"
            value={search}
            placeholder="ID или имя на табло"
            onChange={(e) => setSearch(e.target.value)}
          />
        </label>
        <div className="row" role="group" aria-label="Показать">
          {FILTERS.map((item) => (
            <button
              key={item.id}
              type="button"
              className={filter === item.id ? 'primary' : ''}
              aria-pressed={filter === item.id}
              onClick={() => setFilter(item.id)}
            >
              {item.label}
            </button>
          ))}
        </div>
        <span className="hint">
          Всего {everyone.length} · пришли {arrived}
        </span>
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th rowSpan={2}>ID</th>
              <th rowSpan={2}>Имя на табло</th>
              <th rowSpan={2}>Регистрация</th>
              <th rowSpan={2}>Команда</th>
              {DISCIPLINES.map((discipline) => (
                <th key={discipline} colSpan={SECTIONS.length} className="num">
                  {DISCIPLINE_NAMES[discipline]}
                </th>
              ))}
              <th rowSpan={2}>Действия</th>
            </tr>
            <tr>
              {DISCIPLINES.flatMap((discipline) =>
                SECTIONS.map((section) => (
                  <th key={`${discipline}-${section}`} className="num">
                    {SECTION_HEAD[section]}
                  </th>
                )),
              )}
            </tr>
          </thead>
          <tbody>
            {people.map((person) => (
              <tr key={person.code}>
                <td>
                  <strong>{person.code}</strong>
                </td>
                <td>{person.display_name ?? '—'}</td>
                <td>
                  {person.checked_in ? (
                    <span className="chip good">Пришёл {formatTime(person.checked_in_at).slice(0, 5)}</span>
                  ) : (
                    <span className="chip muted">не пришёл</span>
                  )}
                </td>
                <td className="team">
                  {person.team ? (
                    <>
                      <span className="swatch" style={{ background: person.team.color }} />
                      {person.team.name}
                    </>
                  ) : (
                    '—'
                  )}
                </td>
                {DISCIPLINES.flatMap((discipline) =>
                  SECTIONS.map((section) => {
                    const cell = scoreCell(index, person.code, discipline, section, limits[discipline])
                    const empty = cell.tone === 'none' && cell.text === '—'
                    return (
                      <td key={`${discipline}-${section}`} className="num" title={cell.title}>
                        {empty ? (
                          <span className="hint">—</span>
                        ) : (
                          <span className={cell.tone === 'none' ? 'score' : `chip ${cell.tone}`}>
                            {cell.text}
                          </span>
                        )}
                      </td>
                    )
                  }),
                )}
                <td className="actions no-print">
                  {person.checked_in ? (
                    <button
                      type="button"
                      className="small"
                      aria-label={`Отменить отметку ${person.code}`}
                      onClick={() => void undo(person)}
                    >
                      Отменить
                    </button>
                  ) : (
                    <button
                      type="button"
                      className="small primary"
                      aria-label={`Отметить ${person.code}`}
                      onClick={() => setEditing({ kind: 'check-in', person })}
                    >
                      Отметить
                    </button>
                  )}
                  <button
                    type="button"
                    className="small"
                    aria-label={`Имя ${person.code}`}
                    onClick={() => setEditing({ kind: 'rename', person })}
                  >
                    Имя
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {people.length === 0 && (
          <p className="empty">
            {everyone.length === 0 ? 'Участников пока нет: создайте ID.' : 'Никого не найдено.'}
          </p>
        )}
      </div>

      {editing && (
        <PersonDialog
          api={api}
          editing={editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null)
            list.reload()
          }}
        />
      )}
    </section>
  )
}

interface DialogProps {
  api: StaffApi
  editing: Editing
  onClose: () => void
  onSaved: () => void
}

function PersonDialog({ api, editing, onClose, onSaved }: DialogProps) {
  const { person, kind } = editing
  const action = useAction()
  const [category, setCategory] = useState<Category | null>(null)
  const [name, setName] = useState(person.display_name ?? '')
  const needsCategory = kind === 'check-in'

  async function save(event: FormEvent) {
    event.preventDefault()
    const done = await action.run(() =>
      kind === 'check-in'
        ? api.checkIn(person.code, category as Category, name.trim())
        : api.renameParticipant(person.code, name.trim()),
    )
    if (done) onSaved()
  }

  return (
    <Dialog
      title={kind === 'check-in' ? `Отметка о приходе ${person.code}` : `Имя ${person.code}`}
      onClose={onClose}
    >
      <form className="stack" onSubmit={(e) => void save(e)}>
        {needsCategory && (
          <fieldset className="stack">
            <legend>Категория</legend>
            <label>
              <input
                type="radio"
                name="category"
                checked={category === 'ovz'}
                onChange={() => setCategory('ovz')}
              />{' '}
              С ОВЗ
            </label>
            <label>
              <input
                type="radio"
                name="category"
                checked={category === 'general'}
                onChange={() => setCategory('general')}
              />{' '}
              Без ОВЗ
            </label>
          </fieldset>
        )}
        <label className="field">
          Имя для табло (необязательно)
          <input
            value={name}
            maxLength={MAX_NAME}
            onChange={(e) => setName(e.target.value)}
            placeholder={person.code}
          />
        </label>
        <ErrorText error={action.error} />
        <button
          type="submit"
          className="primary"
          disabled={action.busy || (needsCategory && category === null)}
        >
          Сохранить
        </button>
      </form>
    </Dialog>
  )
}
