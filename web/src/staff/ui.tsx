import { useEffect, useId, useRef, useState } from 'react'
import type { KeyboardEvent, ReactNode, RefObject } from 'react'
import { errorText } from '../shared/messages.ts'

const FOCUSABLE =
  'a[href], button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])'

/**
 * Поведение модального окна: автофокус, Escape, захват Tab, возврат фокуса.
 * Элемент-открыватель запоминается при первом рендере, до автофокуса внутри окна.
 */
function useModal(onClose: () => void): {
  ref: RefObject<HTMLDivElement | null>
  onKeyDown: (event: KeyboardEvent<HTMLDivElement>) => void
} {
  const ref = useRef<HTMLDivElement>(null)
  const [opener] = useState(() => document.activeElement)

  useEffect(() => {
    const root = ref.current
    if (root && !root.contains(document.activeElement)) {
      root.querySelector<HTMLElement>(FOCUSABLE)?.focus()
    }
    return () => {
      if (opener instanceof HTMLElement && opener.isConnected) opener.focus()
    }
  }, [opener])

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === 'Escape') {
      event.stopPropagation()
      onClose()
      return
    }
    if (event.key !== 'Tab' || !ref.current) return
    const items = Array.from(ref.current.querySelectorAll<HTMLElement>(FOCUSABLE))
    const first = items[0]
    const last = items[items.length - 1]
    if (!first || !last) return
    const active = document.activeElement
    if (event.shiftKey && (active === first || !ref.current.contains(active))) {
      event.preventDefault()
      last.focus()
    } else if (!event.shiftKey && (active === last || !ref.current.contains(active))) {
      event.preventDefault()
      first.focus()
    }
  }

  return { ref, onKeyDown }
}

interface DialogProps {
  title: string
  children: ReactNode
  onClose: () => void
}

/** Модальное окно без нативного <dialog>: одинаково работает в браузерах и в тестах. */
export function Dialog({ title, children, onClose }: DialogProps) {
  const { ref, onKeyDown } = useModal(onClose)
  const titleId = useId()
  return (
    <div className="backdrop no-print">
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="dialog stack"
        onKeyDown={onKeyDown}
      >
        <h2 id={titleId}>{title}</h2>
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
  const { ref, onKeyDown } = useModal(onCancel)
  const titleId = useId()
  return (
    <div className="backdrop no-print">
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="dialog stack"
        onKeyDown={onKeyDown}
      >
        <h2 id={titleId}>{title}</h2>
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

export function PrinterIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      width="20"
      height="20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <path d="M7 9V3h10v6M7 17H5a2 2 0 0 1-2-2v-4a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v4a2 2 0 0 1-2 2h-2" />
      <rect x="7" y="14" width="10" height="7" rx="1" />
    </svg>
  )
}
