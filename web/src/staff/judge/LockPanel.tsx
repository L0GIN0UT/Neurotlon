import { useState } from 'react'
import type { StaffApi } from '../api.ts'
import { ConfirmDialog, ErrorText } from '../ui.tsx'
import { useAction } from '../hooks.ts'

/** «Зафиксировать итоги» с двойным подтверждением: после этого судья уже не правит (решение 22). */
export function LockPanel({ api }: { api: StaffApi }) {
  const action = useAction()
  const [step, setStep] = useState<0 | 1 | 2>(0)
  const [locked, setLocked] = useState<number | null>(null)

  async function lock() {
    const result = await action.run(() => api.lockResults())
    setStep(0)
    if (result) setLocked(result.locked)
  }

  return (
    <section className="card stack">
      <h2>Итоги</h2>
      <p>
        Подтверждённые результаты станут заблокированными. После этого их правит только админ.
        Действие нельзя отменить.
      </p>
      <ErrorText error={action.error} />
      {locked !== null && (
        <p role="status">
          {locked > 0 ? `Зафиксировано результатов: ${locked}` : 'Новых результатов для фиксации нет'}
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
          onConfirm={() => void lock()}
          onCancel={() => setStep(0)}
        />
      )}
    </section>
  )
}
