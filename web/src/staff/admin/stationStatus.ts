// Тексты статуса станции. «В сети» определяет сервер (сигнал за последние 30 секунд);
// здесь только подписи и давность сигнала от текущего времени браузера.

export const ONLINE_HINT = 'В сети значит, что станция прислала сигнал за последние 30 секунд.'

export const QUEUE_HINT = 'результаты сохранены на стенде и уйдут на сервер при появлении связи'

const STATE_NAMES: Record<string, string> = {
  idle: 'Ждёт участника',
  confirming: 'Подтверждение участника',
  calibrating: 'Запуск игры, калибровка',
  playing: 'Идёт игра',
  sending: 'Отправка результатов',
}

export function stateName(state: string): string {
  return STATE_NAMES[state] ?? state
}

const pad = (n: number) => String(n).padStart(2, '0')

/** Строка под статусом «В сети»: «сигнал 12 с назад» / «сигнал 3 мин назад». */
export function onlineAgo(iso: string | null, now: number): string | null {
  if (!iso) return null
  const seconds = Math.max(0, Math.floor((now - new Date(iso).getTime()) / 1000))
  return seconds < 60 ? `сигнал ${seconds} с назад` : `сигнал ${Math.floor(seconds / 60)} мин назад`
}

/** Строка под статусом «Не в сети»: время, а если сигнал был не сегодня, то и дата. */
export function lastSeen(iso: string | null, now: number): string {
  if (!iso) return 'ещё ни разу не подключалась'
  const at = new Date(iso)
  const time = `${pad(at.getHours())}:${pad(at.getMinutes())}`
  if (at.toDateString() === new Date(now).toDateString()) return `последний сигнал в ${time}`
  return `последний сигнал ${pad(at.getDate())}.${pad(at.getMonth() + 1)} в ${time}`
}
