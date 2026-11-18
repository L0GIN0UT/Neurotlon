import { useState } from 'react'
import type { FormEvent } from 'react'
import { REASONS, REASON_TEXTS } from '../../shared/messages.ts'
import type { Reason } from '../../shared/types.ts'
import type { StaffApi, StoredResult } from '../api.ts'
import {
  MAX_CHANGE_REASON,
  buildPatch,
  describeResult,
  draftOf,
  pointsLimit,
} from '../resultPatch.ts'
import type { ResultDraft } from '../resultPatch.ts'
import { ErrorText } from '../ui.tsx'
import { useAction } from '../hooks.ts'

const STATUS_NAMES: Record<StoredResult['status'], string> = {
  entered: 'введён',
  confirmed: 'подтверждён',
  locked: 'заблокирован',
}

interface Props {
  api: StaffApi
  row: StoredResult
  /** Заблокированные результаты правят только админ и суперпользователь. */
  canEditLocked: boolean
  /** Лимит очков за секцию дисциплины строки (дартс, футбол); null, пока не загружен. */
  maxPoints?: number | null
  onSaved: (row: StoredResult) => void
}

export function ResultEditor({ api, row, canEditLocked, maxPoints = null, onSaved }: Props) {
  const limit = pointsLimit(row, maxPoints)
  const action = useAction()
  const [draft, setDraft] = useState<ResultDraft>(() => draftOf(row))
  const [formError, setFormError] = useState<string | null>(null)
  const blocked = row.voided
    ? 'Результат аннулирован, правка недоступна.'
    : row.status === 'locked' && !canEditLocked
      ? 'Итоги зафиксированы: заблокированный результат правит админ.'
      : row.status === 'entered'
        ? 'Результат ещё не подтверждён.'
        : null

  function set<K extends keyof ResultDraft>(key: K, value: ResultDraft[K]) {
    setFormError(null)
    setDraft({ ...draft, [key]: value })
  }

  async function save(event: FormEvent) {
    event.preventDefault()
    const built = buildPatch(row, draft, maxPoints)
    if ('error' in built) {
      setFormError(built.error)
      return
    }
    const updated = await action.run(() => api.patchResult(row.id, built.patch))
    if (updated) {
      setDraft(draftOf(updated))
      onSaved(updated)
    }
  }

  return (
    <form className="card stack" noValidate onSubmit={(e) => void save(e)} aria-label={`Правка ${row.id}`}>
      <p>
        <strong>{describeResult(row)}</strong>
        <br />
        <small>
          Статус: {STATUS_NAMES[row.status]}, версия {row.version}, источник: {row.source}
        </small>
      </p>
      {blocked && <p className="warning">{blocked}</p>}
      <fieldset className="row" disabled={blocked !== null}>
        <label className="field">
          Исход
          <select
            value={draft.outcome}
            onChange={(e) => set('outcome', e.target.value as ResultDraft['outcome'])}
          >
            <option value="completed">Пройдено</option>
            <option value="not_completed">Не пройдено</option>
          </select>
        </label>
        {draft.outcome === 'completed' ? (
          <>
            <label className="field">
              Очки
              <input
                type="number"
                min={0}
                max={limit}
                step="any"
                value={draft.points}
                onChange={(e) => set('points', e.target.value)}
              />
            </label>
            {row.discipline === 'pong' && (
              <label className="field">
                <span>
                  <input
                    type="checkbox"
                    checked={draft.wins === '1'}
                    disabled={row.wins === 1}
                    onChange={(e) =>
                      set('wins', e.target.checked ? '1' : row.wins === null ? '' : '0')
                    }
                  />{' '}
                  Победитель
                </span>
                {row.wins === 1 && <small>Чтобы сменить победителя, отметьте другого игрока</small>}
              </label>
            )}
          </>
        ) : (
          <label className="field">
            Причина «не пройдено»
            <select
              value={draft.reason}
              onChange={(e) => set('reason', e.target.value as Reason | '')}
            >
              <option value="">—</option>
              {REASONS.map((reason) => (
                <option key={reason} value={reason}>
                  {REASON_TEXTS[reason]}
                </option>
              ))}
            </select>
          </label>
        )}
        <label className="field grow">
          Комментарий
          <input
            value={draft.comment}
            maxLength={200}
            onChange={(e) => set('comment', e.target.value)}
          />
        </label>
        <label className="field grow">
          Причина исправления (в журнал)
          <input
            value={draft.changeReason}
            maxLength={MAX_CHANGE_REASON}
            onChange={(e) => set('changeReason', e.target.value)}
          />
        </label>
        <button type="submit" className="primary" disabled={action.busy}>
          Сохранить правку
        </button>
      </fieldset>
      <ErrorText error={formError ?? action.error} />
    </form>
  )
}
