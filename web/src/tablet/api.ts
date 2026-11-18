// Типы повторяют shared/openapi.yaml (написаны вручную, без кодогенерации).
// Категория участника в API не передаётся, поэтому её нет и здесь.

export type Discipline = 'darts' | 'football' | 'pong'
export type Section = 'bci' | 'physical'
export type IssueCode =
  | 'not_checked_in'
  | 'already_completed'
  | 'busy_on_other_station'
  | 'no_pair_assigned'
export type Reason = 'participant_refused' | 'health' | 'equipment' | 'no_show' | 'other'
export type Role = 'superuser' | 'admin' | 'judge' | 'volunteer'

export interface Me {
  login: string
  role: Role
  discipline: Discipline | null
}

export interface DisciplineConfig {
  discipline: Discipline
  section: Section
  duration_s: number
}

export interface Team {
  number: number
  name: string
  color: string
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

export interface Correction {
  id: number
  session_id: string
  participant_codes: string[]
  comment: string
  created_at: string
  status: 'open' | 'done'
  resolved_at: string | null
}

/** Ответ сервера с ошибкой (application/problem+json). */
export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly detail: string | undefined

  constructor(status: number, code: string, title: string, detail?: string) {
    super(title)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.detail = detail
  }
}

/** Запрос не дошёл до сервера. */
export class NetworkError extends Error {
  constructor() {
    super('network')
    this.name = 'NetworkError'
  }
}

export interface ApiOptions {
  fetchFn?: typeof fetch
  /** Вызывается при любом 401, кроме входа. */
  onUnauthorized?: () => void
}

const BASE = '/api/v1'

export function createApi({ fetchFn, onUnauthorized }: ApiOptions = {}) {
  async function request<T>(
    method: string,
    path: string,
    body?: unknown,
    isLogin = false,
  ): Promise<T> {
    const doFetch = fetchFn ?? ((input, init) => globalThis.fetch(input, init))
    let response: Response
    try {
      response = await doFetch(`${BASE}${path}`, {
        method,
        credentials: 'include',
        headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
        body: body === undefined ? undefined : JSON.stringify(body),
      })
    } catch {
      throw new NetworkError()
    }
    if (!response.ok) {
      let problem: { code?: string; title?: string; detail?: string } = {}
      try {
        problem = (await response.json()) as typeof problem
      } catch {
        // тело не JSON — оставляем пустую ошибку
      }
      if (response.status === 401 && !isLogin) onUnauthorized?.()
      throw new ApiError(
        response.status,
        problem.code ?? 'unknown',
        problem.title ?? `HTTP ${response.status}`,
        problem.detail,
      )
    }
    if (response.status === 204) return undefined as T
    return (await response.json()) as T
  }

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
