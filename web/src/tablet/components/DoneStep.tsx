import { useEffect, useState } from 'react'
import type { Api, ResultReceipt } from '../api.ts'
import { ApiError } from '../api.ts'
import { ISSUE_TEXTS, errorText } from '../messages.ts'

export const UNDO_WINDOW_S = 30

export type Recorded =
  | { kind: 'recorded'; sessionId: string; recordedAt: number; receipt: ResultReceipt }
  | { kind: 'queued'; sessionId: string }

interface Props {
  api: Api
  result: Recorded
  onNext: () => void
  /** Ввести заново после отмены (новый session_id). */
  onRedo: () => void
}

type Phase = 'undo' | 'correction' | 'undone' | 'requested'

export function DoneStep({ api, result, onNext, onRedo }: Props) {
  const [phase, setPhase] = useState<Phase>('undo')
  const [secondsLeft, setSecondsLeft] = useState(() => leftFor(result))
  const [error, setError] = useState<string | null>(null)
  const [comment, setComment] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (result.kind !== 'recorded' || phase !== 'undo') return
    const timer = setInterval(() => {
      const left = leftFor(result)
      setSecondsLeft(left)
      if (left <= 0) setPhase('correction')
    }, 1000)
    return () => clearInterval(timer)
  }, [result, phase])

  async function undo() {
    setBusy(true)
    setError(null)
    try {
      await api.undoResult(result.sessionId)
      setPhase('undone')
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) setPhase('correction')
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }

  async function requestCorrection() {
    setBusy(true)
    setError(null)
    try {
      await api.createCorrection(result.sessionId, comment.trim())
      setPhase('requested')
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }

  if (result.kind === 'queued') {
    return (
      <section className="card stack">
        <h1>В очереди</h1>
        <p className="warning">
          Нет связи с сервером. Результат сохранён на планшете и отправится сам, как только связь
          появится.
        </p>
        <button type="button" className="primary" onClick={onNext}>
          Следующий участник
        </button>
      </section>
    )
  }

  return (
    <section className="card stack">
      <h1>{phase === 'undone' ? 'Отменено' : 'Записано'}</h1>
      {result.receipt.warnings.length > 0 && (
        <ul className="warning" aria-label="Предупреждения сервера">
          {result.receipt.warnings.map((w, index) => (
            <li key={index}>
              {w.participant_code}: {ISSUE_TEXTS[w.code]}
            </li>
          ))}
        </ul>
      )}
      {phase === 'undo' && (
        <button type="button" onClick={() => void undo()} disabled={busy}>
          Отменить ({secondsLeft} с)
        </button>
      )}
      {phase === 'correction' && (
        <div className="stack">
          <p>Отмена уже недоступна. Можно отправить запрос админу.</p>
          <label className="field">
            Что исправить
            <textarea
              value={comment}
              maxLength={200}
              rows={3}
              onChange={(e) => setComment(e.target.value)}
            />
          </label>
          <button
            type="button"
            onClick={() => void requestCorrection()}
            disabled={busy || comment.trim() === ''}
          >
            Запрос админу на исправление
          </button>
        </div>
      )}
      {phase === 'undone' && (
        <>
          <p>Результат отменён.</p>
          <button type="button" onClick={onRedo}>
            Ввести заново
          </button>
        </>
      )}
      {phase === 'requested' && <p>Запрос отправлен админу.</p>}
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      <button type="button" className="primary" onClick={onNext}>
        Следующий участник
      </button>
    </section>
  )
}

function leftFor(result: Recorded): number {
  if (result.kind !== 'recorded') return 0
  return Math.max(0, UNDO_WINDOW_S - Math.floor((Date.now() - result.recordedAt) / 1000))
}
