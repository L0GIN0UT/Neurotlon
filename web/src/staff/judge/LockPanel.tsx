import { useState } from 'react'
import { ApiError } from '../../shared/http.ts'
import type { StaffApi } from '../api.ts'
import { useAction } from '../hooks.ts'
import { ConfirmDialog, ErrorText } from '../ui.tsx'

interface Blockers {
  conflicts: number
  openCorrections: number
}

function blockersOf(error: unknown): Blockers | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null
  const { conflicts, open_corrections: openCorrections } = error.extra
  if (typeof conflicts !== 'number' || typeof openCorrections !== 'number') return null
  return { conflicts, openCorrections }
}

interface Props {
  api: StaffApi
  /** Фиксировать вопреки блокировкам могут только админ и суперпользователь. */
  canForce: boolean
}

/** «Зафиксировать итоги» с двойным подтверждением: после этого судья уже не правит (решение 22). */
export function LockPanel({ api, canForce }: Props) {
  const action = useAction()
  const [step, setStep] = useState<0 | 1 | 2>(0)
  const [locked, setLocked] = useState<number | null>(null)
  const [forced, setForced] = useState(false)

  async function lock(force: boolean) {
    setLocked(null)
    const result = await action.run(() => api.lockResults(force))
    setStep(0)
    if (result) {
      setLocked(result.locked)
      setForced(force)
    }
  }

  const shown = blockersOf(action.error)

  return (
    <section className="card stack">
      <h2>Итоги</h2>
      <p>
        Подтверждённые результаты станут заблокированными. После этого их правит только админ.
        Действие нельзя отменить.
      </p>
      {shown ? (
        <div className="warning stack" role="alert">
          <strong>Фиксация остановлена:</strong>
          <ul>
            {shown.conflicts > 0 && <li>Неразрешённых конфликтов: {shown.conflicts}</li>}
            {shown.openCorrections > 0 && (
              <li>Открытых запросов на исправление: {shown.openCorrections}</li>
            )}
          </ul>
          {canForce ? (
            <button type="button" disabled={action.busy} onClick={() => void lock(true)}>
              Всё равно зафиксировать
            </button>
          ) : (
            <span>Разберите их или попросите админа зафиксировать вопреки этому.</span>
          )}
        </div>
      ) : (
        <ErrorText error={action.error} />
      )}
      {locked !== null && (
        <p role="status">
          {locked > 0
            ? `Зафиксировано результатов: ${locked}${forced ? ' (принудительно)' : ''}`
            : 'Новых результатов для фиксации нет'}
        </p>
      )}
      <button type="button" className="primary" onClick={() => setStep(1)}>
        Зафиксировать итоги
      </button>
      {step === 1 && (
        <ConfirmDialog
          title="Зафиксировать итоги?"
          message="Все подтверждённые результаты будут заблокированы."
          confirmLabel="Продолжить"
          onConfirm={() => setStep(2)}
          onCancel={() => setStep(0)}
        />
      )}
      {step === 2 && (
        <ConfirmDialog
          title="Точно зафиксировать?"
          message="Последнее подтверждение: судья больше не сможет править эти результаты."
          confirmLabel="Да, зафиксировать"
          busy={action.busy}
          onConfirm={() => void lock(false)}
          onCancel={() => setStep(0)}
        />
      )}
    </section>
  )
}
