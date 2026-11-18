import type { ReactNode } from 'react'
import { errorText } from '../shared/messages.ts'

interface DialogProps {
  title: string
  children: ReactNode
  onClose: () => void
}

/** Модальное окно без нативного <dialog>: одинаково работает в браузерах и в тестах. */
export function Dialog({ title, children, onClose }: DialogProps) {
  return (
    <div className="backdrop no-print">
      <div role="dialog" aria-modal="true" aria-label={title} className="dialog stack">
        <h2>{title}</h2>
        {children}
        <button type="button" className="ghost" onClick={onClose}>
          Закрыть
        </button>
      </div>
    </div>
  )
}

interface ConfirmProps {
  title: string
  message: ReactNode
  confirmLabel: string
  busy?: boolean
  onConfirm: () => void
  onCancel: () => void
}

export function ConfirmDialog({ title, message, confirmLabel, busy, onConfirm, onCancel }: ConfirmProps) {
  return (
    <div className="backdrop no-print">
      <div role="dialog" aria-modal="true" aria-label={title} className="dialog stack">
        <h2>{title}</h2>
        <div>{message}</div>
        <div className="row">
          <button type="button" className="primary" disabled={busy} onClick={onConfirm}>
            {confirmLabel}
          </button>
          <button type="button" onClick={onCancel}>
            Отмена
          </button>
        </div>
      </div>
    </div>
  )
}

export function ErrorText({ error }: { error: unknown }) {
  if (error === null || error === undefined) return null
  return (
    <p role="alert" className="error">
      {typeof error === 'string' ? error : errorText(error)}
    </p>
  )
}
