import { useState } from 'react'
import type { OfflineQueue, QueueSnapshot } from '../offlineQueue.ts'

interface Props {
  queue: OfflineQueue
  snapshot: QueueSnapshot
}

/** Счётчик очереди в шапке и список отклонённых сервером результатов. */
export function QueuePanel({ queue, snapshot }: Props) {
  const [open, setOpen] = useState(false)
  const { pending, failed } = snapshot
  return (
    <div className="queue">
      {pending.length > 0 && <span className="badge warn">В очереди: {pending.length}</span>}
      {failed.length > 0 && (
        <button type="button" className="badge bad" onClick={() => setOpen((v) => !v)}>
          Ошибки: {failed.length}
        </button>
      )}
      {open && failed.length > 0 && (
        <ul className="card errors" aria-label="Ошибки отправки">
          {failed.map((item) => (
            <li key={item.sessionId}>
              <span>
                {item.payload.entries.map((e) => e.participant_code).join(', ')}:{' '}
                {item.error ?? 'Сервер отклонил результат'}
              </span>
              <button type="button" onClick={() => void queue.dismiss(item.sessionId)}>
                Убрать
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
