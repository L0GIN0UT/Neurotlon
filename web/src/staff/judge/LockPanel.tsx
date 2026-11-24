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
  /** Невыполненные пункты чек-листа: показываются в окне подтверждения. */
  warnings?: string[]
  /** Вызывается после успешной фиксации (обновить счётчики). */
  onLocked?: () => void
}

/** «Зафиксировать итоги» с двойным подтверждением: после этого судья уже не правит (решение 22). */
export function LockPanel({ api, canForce, warnings = [], onLocked }: Props) {
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
      onLocked?.()
    }
  }

  const shown = blockersOf(action.error)

  return (
    <section className="card summary-action lock">
      <div className="head">
        <svg
          className="icon"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <rect x="5" y="11" width="14" height="9" rx="2" />
          <path d="M8 11V8a4 4 0 0 1 8 0v3" />
        </svg>
        <h2>Зафиксировать итоги</h2>
      </div>
      <p>
        Все подтверждённые результаты станут заблокированными: после этого судья их уже не
        правит, только админ.
      </p>
      <p className="irreversible">Это действие нельзя отменить.</p>
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
      <button type="button" className="primary push" onClick={() => setStep(1)}>
        Зафиксировать итоги
      </button>
      {step === 1 && (
        <ConfirmDialog
          title="Зафиксировать итоги?"
          message={
            <>
              <p>Все подтверждённые результаты будут заблокированы.</p>
              {warnings.length > 0 && (
                <div className="warning stack">
                  <strong>Не всё готово:</strong>
                  <ul>
                    {warnings.map((w) => (
                      <li key={w}>{w}</li>
                    ))}
                  </ul>
                </div>
              )}
            </>
          }
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
