// Типы повторяют shared/openapi.yaml (написаны вручную, без кодогенерации).
// Категория участника в API не передаётся, поэтому её нет и здесь.

import { createRequester } from '../shared/http.ts'
import type { ApiOptions } from '../shared/http.ts'
import type { Correction, Discipline, Me, Reason, Section, Team } from '../shared/types.ts'

export { ApiError, NetworkError } from '../shared/http.ts'
export type { ApiOptions } from '../shared/http.ts'
export type { Correction, Discipline, Me, Reason, Role, Section, Team } from '../shared/types.ts'

export type IssueCode =
  | 'not_checked_in'
  | 'already_completed'
  | 'busy_on_other_station'
  | 'no_pair_assigned'

export interface DisciplineConfig {
  discipline: Discipline
  section: Section
  duration_s: number
  /** Лимит очков за секцию дартса и футбола; у понга null. Нет в старой копии настроек. */
  max_points?: number | null
}

export interface Eligibility {
  code: string
  display_name: string | null
  team: Team | null
  issues: IssueCode[]
}

export interface ResultEntry {
  participant_code: string
  outcome: 'completed' | 'not_completed'
  points?: number
  wins?: number
  reason?: Reason
  comment?: string
}

export interface ResultSubmission {
  session_id: string
  discipline: Discipline
  section: Section
  finished_at: string
  entries: ResultEntry[]
}

export interface ResultReceipt {
  session_id: string
  results: { id: number; participant_code: string; status: 'entered' | 'confirmed' | 'locked' }[]
  warnings: { participant_code: string; code: IssueCode }[]
}

export function createApi(options: ApiOptions = {}) {
  const request = createRequester(options)

  return {
    login: (login: string, password: string) =>
      request<void>('POST', '/auth/login', { login, password }, true),
    logout: () => request<void>('POST', '/auth/logout'),
    me: () => request<Me>('GET', '/auth/me'),
    config: () => request<DisciplineConfig>('GET', '/me/config'),
    eligibility: (code: string, discipline: Discipline, section: Section) =>
      request<Eligibility>(
        'GET',
        `/participants/${encodeURIComponent(code)}/eligibility?discipline=${discipline}&section=${section}`,
      ),
    submitResult: (payload: ResultSubmission) =>
      request<ResultReceipt>('POST', '/results', payload),
    undoResult: (sessionId: string) =>
      request<void>('POST', `/results/${encodeURIComponent(sessionId)}/undo`),
    createCorrection: (sessionId: string, comment: string) =>
      request<Correction>('POST', '/corrections', { session_id: sessionId, comment }),
  }
}

export type Api = ReturnType<typeof createApi>
