import { useEffect, useState } from 'react'
import type { Discipline, Reason } from '../api.ts'
import { REASONS, REASON_TEXTS } from '../messages.ts'
import { emptyForm, sectionPointsProblem, stepPoints, toEntries } from '../entryForm.ts'
import type { EntryDraft, PersonForm } from '../entryForm.ts'
import { PayloadError } from '../payload.ts'
import type { EntryInput } from '../payload.ts'
import { personLabel } from '../people.ts'
import type { Person } from '../people.ts'
import { POINTS_MAX, POINTS_STEP, sectionLimit } from '../scoring/placeholder.ts'

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${m}:${String(s).padStart(2, '0')}`
}

/** Таймер для волонтёра: только подсказка, на запись не влияет. */
export function Timer({ durationS }: { durationS: number }) {
  const [left, setLeft] = useState(durationS)
  const [running, setRunning] = useState(false)

  useEffect(() => {
    if (!running) return
    const timer = setInterval(() => setLeft((value) => Math.max(0, value - 1)), 1000)
    return () => clearInterval(timer)
  }, [running])

  const over = left === 0
  return (
    <div className="timer" role="timer" aria-label="Таймер секции">
      <output className={over ? 'over' : ''}>{formatTime(left)}</output>
      {over && <span>Время вышло</span>}
      <button type="button" onClick={() => setRunning((on) => !on)} disabled={over}>
        {running ? 'Стоп' : 'Старт'}
      </button>
      <button
        type="button"
        onClick={() => {
          setRunning(false)
          setLeft(durationS)
        }}
      >
        Сбросить
      </button>
    </div>
  )
}

interface FieldsProps {
  discipline: Discipline
  form: PersonForm
  maxPoints: number | null
  onChange: (form: PersonForm) => void
}

function SectionFields({
  form,
  maxPoints,
  onChange,
}: Pick<FieldsProps, 'form' | 'onChange'> & { maxPoints: number | null }) {
  const limit = sectionLimit(maxPoints)
  const problem = sectionPointsProblem(form.points, maxPoints)
  return (
    <div className="stack">
      <div className="stepper">
        <button
          type="button"
          aria-label="Уменьшить очки за секцию на 1"
          onClick={() => onChange({ ...form, points: stepPoints(form.points, -1, maxPoints) })}
        >
          −
        </button>
        <label className="field grow">
          Очки за секцию
          <input
            type="number"
            inputMode="numeric"
            min={0}
            max={limit}
            step={POINTS_STEP}
            value={form.points}
            onChange={(e) => onChange({ ...form, points: e.target.value })}
          />
        </label>
        <button
          type="button"
          aria-label="Увеличить очки за секцию на 1"
          onClick={() => onChange({ ...form, points: stepPoints(form.points, 1, maxPoints) })}
        >
          +
        </button>
      </div>
      <p className={problem ? 'error' : 'hint'}>
        {problem ?? `Целое число от 0 до ${limit}`}
      </p>
    </div>
  )
}

function PongFields({ form, onChange }: Pick<FieldsProps, 'form' | 'onChange'>) {
  return (
    <label className="field">
      Очки
      <input
        type="number"
        inputMode="numeric"
        min={0}
        max={POINTS_MAX}
        value={form.points}
        onChange={(e) => onChange({ ...form, points: e.target.value })}
      />
    </label>
  )
}

function PersonEntry({
  discipline,
  person,
  heading,
  form,
  maxPoints,
  onChange,
}: FieldsProps & { person: Person; heading: string | null }) {
  const name = personLabel(person)
  return (
    <fieldset className="stack">
      <legend>{heading ? `${heading}: ${name}` : name}</legend>
      <div className="row segmented" role="group" aria-label={`Итог: ${name}`}>
        <button
          type="button"
          className={form.completed ? 'toggle on' : 'toggle'}
          aria-pressed={form.completed}
          onClick={() => onChange({ ...form, completed: true })}
        >
          Пройдено
        </button>
        <button
          type="button"
          className={form.completed ? 'toggle' : 'toggle on'}
          aria-pressed={!form.completed}
          onClick={() => onChange({ ...form, completed: false })}
        >
          Не пройдено
        </button>
      </div>
      {form.completed ? (
        <>
          {discipline === 'pong' ? (
            <PongFields form={form} onChange={onChange} />
          ) : (
            <SectionFields form={form} maxPoints={maxPoints} onChange={onChange} />
          )}
        </>
      ) : (
        <div className="stack">
          <label className="field">
            Причина
            <select
              value={form.reason}
              onChange={(e) => onChange({ ...form, reason: e.target.value as Reason })}
            >
              {REASONS.map((reason) => (
                <option key={reason} value={reason}>
                  {REASON_TEXTS[reason]}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            Комментарий (необязательно)
            <input
              value={form.comment}
              maxLength={200}
              onChange={(e) => onChange({ ...form, comment: e.target.value })}
            />
          </label>
        </div>
      )}
    </fieldset>
  )
}

interface Props {
  discipline: Discipline
  people: Person[]
  durationS: number
  /** Лимит очков за секцию (дартс, футбол); у понга null. */
  maxPoints: number | null
  draft: EntryDraft
  onDraft: (draft: EntryDraft) => void
  onBack: () => void
  onNext: (entries: EntryInput[], winner: string | null) => void
}

export function EntryStep({
  discipline,
  people,
  durationS,
  maxPoints,
  draft,
  onDraft,
  onBack,
  onNext,
}: Props) {
  const [error, setError] = useState<string | null>(null)
  const completedPeople = people.filter((p) => draft.forms[p.code]?.completed ?? true)

  function next() {
    try {
      const { entries, winner } = toEntries(discipline, people, draft, maxPoints)
      setError(null)
      onNext(entries, winner)
    } catch (e) {
      setError(e instanceof PayloadError ? e.message : 'Проверьте введённые данные')
    }
  }

  return (
    <section className="card stack">
      <h1>Ввод результата</h1>
      <Timer durationS={durationS} />
      {people.map((person, index) => (
        <PersonEntry
          key={person.code}
          discipline={discipline}
          person={person}
          heading={discipline === 'pong' ? `Игрок ${index + 1}` : null}
          form={draft.forms[person.code] ?? emptyForm()}
          maxPoints={maxPoints}
          onChange={(form) => onDraft({ ...draft, forms: { ...draft.forms, [person.code]: form } })}
        />
      ))}
      {discipline === 'pong' && (
        <fieldset className="stack">
          <legend>Победитель</legend>
          <div className="row segmented">
            {completedPeople.map((person) => (
              <button
                key={person.code}
                type="button"
                className={draft.winner === person.code ? 'toggle on' : 'toggle'}
                aria-pressed={draft.winner === person.code}
                onClick={() => onDraft({ ...draft, winner: person.code })}
              >
                Победил {personLabel(person)}
              </button>
            ))}
          </div>
        </fieldset>
      )}
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      <div className="row">
        <button type="button" onClick={onBack}>
          Назад
        </button>
        <button type="button" className="primary" onClick={next}>
          К сводке
        </button>
      </div>
    </section>
  )
}
