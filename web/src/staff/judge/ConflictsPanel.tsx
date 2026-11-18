import { useState } from 'react'
import { DISCIPLINE_NAMES, SECTION_NAMES } from '../../shared/messages.ts'
import type { Conflict, StaffApi } from '../api.ts'
import { ErrorText } from '../ui.tsx'
import { formatTime } from '../format.ts'
import { useAction, useLoader } from '../hooks.ts'

export function ConflictsPanel({ api }: { api: StaffApi }) {
  const list = useLoader(() => api.conflicts())
  const conflicts = list.data ?? []
  return (
    <section className="stack">
      <p>
        Два результата на одну секцию: пока судья не оставит один, секция не даёт очков и на табло
        помечена «нужно решение».
      </p>
      <ErrorText error={list.error} />
      {list.data && conflicts.length === 0 && <p className="card">Конфликтов нет.</p>}
      {conflicts.map((conflict) => (
        <ConflictCard
          key={`${conflict.participant_code}-${conflict.discipline}-${conflict.section}`}
          api={api}
          conflict={conflict}
          onResolved={list.reload}
        />
      ))}
    </section>
  )
}

interface CardProps {
  api: StaffApi
  conflict: Conflict
  onResolved: () => void
}

function ConflictCard({ api, conflict, onResolved }: CardProps) {
  const action = useAction()
  const [keep, setKeep] = useState<number | null>(null)
  const [reason, setReason] = useState('')
  const title = `${conflict.participant_code} · ${DISCIPLINE_NAMES[conflict.discipline]} · ${SECTION_NAMES[conflict.section]}`

  async function resolve() {
    if (keep === null) return
    if (await action.run(() => api.resolveConflict(keep, reason.trim()))) onResolved()
  }

  return (
    <article className="card stack" aria-label={title}>
      <h2>{title}</h2>
      <ul className="plain">
        {conflict.results.map((result) => (
          <li key={result.id}>
            <label>
              <input
                type="radio"
                name={`keep-${conflict.participant_code}-${conflict.discipline}-${conflict.section}`}
                checked={keep === result.id}
                onChange={() => setKeep(result.id)}
              />{' '}
              Оставить №{result.id}:{' '}
              {result.outcome === 'completed'
                ? `очки ${result.points ?? 0}${result.wins === null ? '' : `, побед ${result.wins}`}`
                : 'не пройдено'}
              , источник {result.source}, {formatTime(result.finished_at)}
            </label>
          </li>
        ))}
      </ul>
      <label className="field">
        Причина решения
        <input value={reason} maxLength={200} onChange={(e) => setReason(e.target.value)} />
      </label>
      <ErrorText error={action.error} />
      <button
        type="button"
        className="primary"
        disabled={keep === null || reason.trim() === '' || action.busy}
        onClick={() => void resolve()}
      >
        Решить конфликт {title}
      </button>
    </article>
  )
}
