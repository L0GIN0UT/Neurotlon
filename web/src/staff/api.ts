// Клиент админки и судьи. Типы повторяют ответы сервера (shared/openapi.yaml, server/README.md).
// Категория участника есть только в запросах и ответах админки (регистрация, протокол жеребьёвки);
// на табло и в экспорт она не попадает.

import { createRequester, query } from '../shared/http.ts'
import type { ApiOptions } from '../shared/http.ts'
import type { Correction, Discipline, Me, Reason, Role, Section, Team } from '../shared/types.ts'

export type Category = 'general' | 'ovz'

export interface Participant {
  code: string
  display_name: string | null
  checked_in: boolean
  checked_in_at: string | null
  team: Team | null
  category?: Category | null
}

export interface DrawOption {
  m: number
  team_count: number
  reserve_general: number
  reserve_ovz: number
  reserve_total: number
}

export interface DrawProtocol {
  id: number
  created_at: string
  seed: number
  m: number
  team_count: number
  teams: {
    number: number
    name: string
    color: string
    members: { code: string; number_in_team: number }[]
  }[]
  duels: { order: number; team_a: number; team_b: number; pairs: { k: number; a: string; b: string }[] }[]
  reserve_ovz: string[]
  reserve_general: string[]
}

export interface TeamInfo {
  id: number
  number: number
  name: string
  color: string
}

export interface StationInfo {
  id: number
  name: string
  discipline: Discipline
  online: boolean
  last_heartbeat_at: string | null
  last_state: string | null
  queue_length: number
}

/** Токен приходит только при создании и ротации. */
export interface StationWithToken {
  id: number
  name: string
  discipline: Discipline
  token: string
}

export interface DisciplineSettings {
  code: Discipline
  game_duration_s: number
  physical_duration_s: number
  win_points: number
  /** Лимит очков за секцию дартса и футбола; понг им не ограничен. */
  max_section_points: number
}

export interface UserInfo {
  id: number
  login: string
  role: Role
  discipline: Discipline | null
  is_active: boolean
}

export interface NewUser {
  login: string
  password: string
  role: Exclude<Role, 'superuser'>
  discipline?: Discipline
}

export interface ConflictResult {
  id: number
  points: number | null
  wins: number | null
  outcome: 'completed' | 'not_completed'
  reason: string | null
  source: string
  finished_at: string
  created_at: string
}

export interface Conflict {
  participant_code: string
  discipline: Discipline
  section: Section
  results: ConflictResult[]
}

export interface StoredResult {
  id: number
  session_id: string
  participant_code: string
  discipline: Discipline
  section: Section
  outcome: 'completed' | 'not_completed'
  points: number | null
  wins: number | null
  reason: Reason | null
  comment: string | null
  status: 'entered' | 'confirmed' | 'locked'
  source: string
  finished_at: string
  version: number
  voided: boolean
}

export interface ResultPatch {
  points?: number
  wins?: number
  outcome?: 'completed' | 'not_completed'
  reason?: Reason
  comment?: string | null
  change_reason: string
}

export type ResultFilter = {
  participant?: string
  discipline?: Discipline | ''
  section?: Section | ''
  session_id?: string
}

export const BADGES_URL = '/api/v1/participants/badges.pdf'
export const EXPORT_URL = '/api/v1/export.xlsx'

export function createStaffApi(options: ApiOptions = {}) {
  const request = createRequester(options)
  const code = encodeURIComponent

  return {
    login: (login: string, password: string) =>
      request<void>('POST', '/auth/login', { login, password }, true),
    logout: () => request<void>('POST', '/auth/logout'),
    me: () => request<Me>('GET', '/auth/me'),

    participants: () => request<Participant[]>('GET', '/participants'),
    generateParticipants: (count: number) =>
      request<{ created: string[]; total: number }>('POST', '/participants/generate', { count }),
    checkIn: (participant: string, category: Category, displayName: string) =>
      request<Participant>('POST', `/participants/${code(participant)}/check-in`, {
        category,
        display_name: displayName,
      }),
    undoCheckIn: (participant: string) =>
      request<Participant>('DELETE', `/participants/${code(participant)}/check-in`),
    renameParticipant: (participant: string, displayName: string) =>
      request<Participant>('PATCH', `/participants/${code(participant)}`, {
        display_name: displayName,
      }),

    drawOptions: () => request<DrawOption[]>('GET', '/draw/options'),
    runDraw: (m: number, seed?: number) =>
      request<{ id: number; seed: number; m: number; team_count: number }>(
        'POST',
        '/draw',
        seed === undefined ? { m } : { m, seed },
      ),
    draw: () => request<DrawProtocol>('GET', '/draw'),
    teams: () => request<{ teams: TeamInfo[] }>('GET', '/teams'),
    patchTeam: (id: number, name: string, color: string) =>
      request<TeamInfo>('PATCH', `/teams/${id}`, { name, color }),

    stations: () => request<StationInfo[]>('GET', '/stations'),
    createStation: (name: string, discipline: Discipline) =>
      request<StationWithToken>('POST', '/stations', { name, discipline }),
    rotateStationToken: (id: number) =>
      request<StationWithToken>('POST', `/stations/${id}/rotate-token`),

    disciplines: () => request<DisciplineSettings[]>('GET', '/disciplines'),
    patchDiscipline: (
      discipline: Discipline,
      changes: Partial<Omit<DisciplineSettings, 'code'>>,
    ) => request<DisciplineSettings>('PATCH', `/disciplines/${discipline}`, changes),

    users: () => request<UserInfo[]>('GET', '/users'),
    createUser: (user: NewUser) => request<UserInfo>('POST', '/users', user),
    patchUser: (id: number, changes: { is_active?: boolean; password?: string }) =>
      request<UserInfo>('PATCH', `/users/${id}`, changes),
    revokeSessions: (id: number) => request<void>('POST', `/users/${id}/revoke-sessions`),

    conflicts: () => request<Conflict[]>('GET', '/conflicts'),
    resolveConflict: (keepResultId: number, reason: string) =>
      request<{ voided: number[] }>('POST', '/conflicts/resolve', {
        keep_result_id: keepResultId,
        reason,
      }),

    corrections: (status: 'open' | 'done') =>
      request<Correction[]>('GET', `/corrections${query({ status })}`),
    finishCorrection: (id: number) => request<Correction>('POST', `/corrections/${id}/done`),

    results: (filter: ResultFilter) =>
      request<{ total: number; items: StoredResult[] }>('GET', `/results${query(filter)}`),
    /** Все результаты (постранично, по 1000). */
    allResults: async (): Promise<StoredResult[]> => {
      const all: StoredResult[] = []
      for (;;) {
        const page = await request<{ total: number; items: StoredResult[] }>(
          'GET',
          `/results${query({ limit: '1000', offset: String(all.length) })}`,
        )
        all.push(...page.items)
        if (page.items.length === 0 || all.length >= page.total) return all
      }
    },
    patchResult: (id: number, patch: ResultPatch) =>
      request<StoredResult>('PATCH', `/results/${id}`, patch),
    lockResults: (force = false) =>
      request<{ locked: number }>('POST', '/results/lock', force ? { force: true } : undefined),
  }
}

export type StaffApi = ReturnType<typeof createStaffApi>
