import type { Discipline } from '../api.ts'
import { DISCIPLINE_NAMES, REASON_TEXTS } from '../messages.ts'
import type { EntryInput } from '../payload.ts'
import { personLabel } from '../people.ts'
import type { Person } from '../people.ts'

interface Props {
  discipline: Discipline
  people: Person[]
  entries: EntryInput[]
  winner: string | null
  busy: boolean
  error: string | null
  /** Ошибку не исправить повтором: остаётся только начать заново. */
  errorFinal: boolean
  onBack: () => void
  onSubmit: () => void
  onRestart: () => void
}

export function SummaryStep({
  discipline,
  people,
  entries,
  winner,
  busy,
  error,
  errorFinal,
  onBack,
  onSubmit,
  onRestart,
}: Props) {
  return (
    <section className="card stack">
      <h1>Сводка</h1>
      <p>{DISCIPLINE_NAMES[discipline]}</p>
      <ul className="summary">
        {entries.map((entry) => {
          const person = people.find((p) => p.code === entry.code)
          const name = person ? personLabel(person) : entry.code
          return (
            <li key={entry.code}>
              <strong>{name}</strong>
              {entry.completed ? (
                <span>
                  Очки: {entry.points}
                  {discipline === 'pong' && winner !== null && (
                    <> {winner === entry.code ? '· победа' : '· поражение'}</>
                  )}
                </span>
              ) : (
                <span>
                  Не пройдено: {REASON_TEXTS[entry.reason]}
                  {entry.comment?.trim() ? ` (${entry.comment.trim()})` : ''}
                </span>
              )}
            </li>
          )
        })}
      </ul>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      <div className="row">
        {errorFinal ? (
          <button type="button" onClick={onRestart}>
            Вернуться к началу
          </button>
        ) : (
          <>
            <button type="button" onClick={onBack} disabled={busy}>
              Назад
            </button>
            <button type="button" className="primary" onClick={onSubmit} disabled={busy}>
              Записать
            </button>
          </>
        )}
      </div>
    </section>
  )
}
