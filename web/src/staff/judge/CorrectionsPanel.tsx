import { useState } from 'react'
import type { Correction, Discipline } from '../../shared/types.ts'
import type { StaffApi, StoredResult } from '../api.ts'
import { ErrorText } from '../ui.tsx'
import { formatTime } from '../format.ts'
import { useAction, useLoader } from '../hooks.ts'
import { ResultEditor } from './ResultEditor.tsx'

interface Props {
  api: StaffApi
  canEditLocked: boolean
  /** Лимит очков за секцию по дисциплинам. */
  limits?: Partial<Record<Discipline, number>>
}

export function CorrectionsPanel({ api, canEditLocked, limits = {} }: Props) {
  const list = useLoader(() => api.corrections('open'))
  const corrections = list.data ?? []
  return (
    <section className="stack">
      <ErrorText error={list.error} />
      {list.data && corrections.length === 0 && <p className="card">Открытых запросов нет.</p>}
      {corrections.map((correction) => (
        <CorrectionCard
          key={correction.id}
          api={api}
          correction={correction}
          canEditLocked={canEditLocked}
          limits={limits}
          onDone={list.reload}
        />
      ))}
    </section>
  )
}

interface CardProps extends Props {
  correction: Correction
  onDone: () => void
}

function CorrectionCard({ api, correction, canEditLocked, limits = {}, onDone }: CardProps) {
  const action = useAction()
  const [rows, setRows] = useState<StoredResult[] | null>(null)
  const label = `Запрос ${correction.id}`

  async function open() {
    const found = await action.run(() => api.results({ session_id: correction.session_id }))
    if (found) setRows(found.items)
  }

  async function finish() {
    if (await action.run(() => api.finishCorrection(correction.id))) onDone()
  }

  return (
    <article className="card stack" aria-label={label}>
      <h2>
        {label}: {correction.participant_codes.join(', ')}
      </h2>
      <p>
        «{correction.comment}» <small>({formatTime(correction.created_at)})</small>
      </p>
      <div className="row">
        <button type="button" onClick={() => void open()} disabled={action.busy}>
          Открыть результат {correction.id}
        </button>
        <button type="button" className="primary" onClick={() => void finish()} disabled={action.busy}>
          Отметить выполненным {correction.id}
        </button>
      </div>
      <ErrorText error={action.error} />
      {rows?.length === 0 && <p>Результаты этой записи не найдены.</p>}
      {rows?.map((row) => (
        <ResultEditor
          key={row.id}
          api={api}
          row={row}
          canEditLocked={canEditLocked}
          maxPoints={limits[row.discipline] ?? null}
          onSaved={(saved) =>
            setRows((current) => current?.map((r) => (r.id === saved.id ? saved : r)) ?? null)
          }
        />
      ))}
    </article>
  )
}
