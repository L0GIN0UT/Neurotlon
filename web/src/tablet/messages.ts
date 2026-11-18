import { ApiError, NetworkError } from './api.ts'
import type { Discipline, IssueCode, Reason } from './api.ts'

export const DISCIPLINE_NAMES: Record<Discipline, string> = {
  darts: 'Дартс',
  football: 'Футбол',
  pong: 'Понг',
}

export const ISSUE_TEXTS: Record<IssueCode, string> = {
  not_checked_in: 'Нет отметки о регистрации',
  already_completed: 'Эту секцию участник уже проходил',
  busy_on_other_station: 'Участник сейчас играет на другом стенде',
  no_pair_assigned: 'Участнику не назначена пара',
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

/** Текст ошибки для волонтёра. */
export function errorText(error: unknown): string {
  if (error instanceof NetworkError) return 'Нет связи с сервером'
  if (error instanceof ApiError) {
    return PROBLEM_TEXTS[error.code] ?? error.detail ?? 'Сервер отклонил запрос'
  }
  return 'Что-то пошло не так'
}
