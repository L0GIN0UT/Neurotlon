// Типы повторяют shared/openapi.yaml (написаны вручную, без кодогенерации).

export type Discipline = 'darts' | 'football' | 'pong'
export type Section = 'bci' | 'physical'
export type Reason = 'participant_refused' | 'health' | 'equipment' | 'no_show' | 'other'
export type Role = 'superuser' | 'admin' | 'judge' | 'volunteer'

export interface Me {
  login: string
  role: Role
  discipline: Discipline | null
}

export interface Team {
  number: number
  name: string
  color: string
}

export interface Correction {
  id: number
  session_id: string
  participant_codes: string[]
  comment: string
  created_at: string
  status: 'open' | 'done'
  resolved_at: string | null
}

export const DISCIPLINES: Discipline[] = ['darts', 'football', 'pong']
