import type { IssueCode } from './api.ts'

export { DISCIPLINE_NAMES, REASONS, REASON_TEXTS, errorText } from '../shared/messages.ts'

export const ISSUE_TEXTS: Record<IssueCode, string> = {
  not_checked_in: 'Нет отметки о регистрации',
  already_completed: 'Эту секцию участник уже проходил',
  busy_on_other_station: 'Участник сейчас играет на другом стенде',
  no_pair_assigned: 'Участнику не назначена пара',
}
