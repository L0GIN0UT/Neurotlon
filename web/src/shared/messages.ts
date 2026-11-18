import { ApiError, NetworkError } from './http.ts'
import type { Discipline, Reason, Section } from './types.ts'

export const DISCIPLINE_NAMES: Record<Discipline, string> = {
  darts: 'Дартс',
  football: 'Футбол',
  pong: 'Понг',
}

export const SECTION_NAMES: Record<Section, string> = {
  bci: 'BCI',
  physical: 'Физическая',
}

export const REASON_TEXTS: Record<Reason, string> = {
  participant_refused: 'Участник отказался',
  health: 'Самочувствие',
  equipment: 'Неисправность оборудования',
  no_show: 'Не явился',
  other: 'Другое',
}

export const REASONS = Object.keys(REASON_TEXTS) as Reason[]

const PROBLEM_TEXTS: Record<string, string> = {
  session_conflict: 'Этот номер записи уже использован с другими данными',
  invalid_entries: 'Данные участников не подходят для этой секции',
  wrong_discipline: 'Это не ваша секция',
  unknown_participant: 'Участник с таким ID не найден',
  result_voided: 'Эта запись уже отменена. Введите результат заново',
  conflict: 'Действие уже недоступно',
  forbidden: 'Нет доступа',
  too_many_attempts: 'Слишком много попыток, подождите несколько минут',
}

/** Текст ошибки для человека. */
export function errorText(error: unknown): string {
  if (error instanceof NetworkError) return 'Нет связи с сервером'
  if (error instanceof ApiError) {
    return PROBLEM_TEXTS[error.code] ?? error.detail ?? 'Сервер отклонил запрос'
  }
  return 'Что-то пошло не так'
}
