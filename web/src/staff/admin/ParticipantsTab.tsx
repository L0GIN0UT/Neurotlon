import { useState } from 'react'
import type { FormEvent } from 'react'
import type { Category, Participant, StaffApi } from '../api.ts'
import { BADGES_URL } from '../api.ts'
import { Dialog, ErrorText } from '../ui.tsx'
import { formatTime } from '../format.ts'
import { useAction, useLoader } from '../hooks.ts'

const MAX_NAME = 24

type Editing =
  | { kind: 'check-in'; person: Participant }
  | { kind: 'rename'; person: Participant }

export function ParticipantsTab({ api }: { api: StaffApi }) {
  const list = useLoader(() => api.participants())
  const action = useAction()
  const [count, setCount] = useState('20')
  const [editing, setEditing] = useState<Editing | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

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

  const people = list.data ?? []
  return (
    <section className="stack">
      <form className="row card" onSubmit={(e) => void generate(e)}>
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
        <button
          type="button"
          disabled={people.length === 0}
          onClick={() => window.open(BADGES_URL, '_blank')}
        >
          Печать бейджей
        </button>
        {notice && <span role="status">{notice}</span>}
      </form>
      <ErrorText error={action.error ?? list.error} />

      <table className="card">
        <thead>
          <tr>
            <th>ID</th>
            <th>Имя на табло</th>
            <th>Регистрация</th>
            <th>Команда</th>
            <th>Действия</th>
          </tr>
        </thead>
        <tbody>
          {people.map((person) => (
            <tr key={person.code}>
              <td>
                <strong>{person.code}</strong>
              </td>
              <td>{person.display_name ?? '—'}</td>
              <td>{person.checked_in ? `Пришёл ${formatTime(person.checked_in_at)}` : '—'}</td>
              <td>
                {person.team ? (
                  <>
                    <span className="swatch" style={{ background: person.team.color }} />
                    {person.team.name}
                  </>
                ) : (
                  '—'
                )}
              </td>
              <td className="actions">
                {person.checked_in ? (
                  <button type="button" onClick={() => void undo(person)}>
                    Отменить отметку {person.code}
                  </button>
                ) : (
                  <button type="button" onClick={() => setEditing({ kind: 'check-in', person })}>
                    Отметить {person.code}
                  </button>
                )}
                <button type="button" onClick={() => setEditing({ kind: 'rename', person })}>
                  Имя {person.code}
                </button>
              </td>
            </tr>
          ))}
          {people.length === 0 && (
            <tr>
              <td colSpan={5}>Участников пока нет: создайте ID.</td>
            </tr>
          )}
        </tbody>
      </table>

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
