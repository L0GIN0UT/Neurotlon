// Общий HTTP-клиент для планшета, админки и судьи: cookie сессии, application/problem+json.

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

export const API_BASE = '/api/v1'

export type Requester = <T>(
  method: string,
  path: string,
  body?: unknown,
  isLogin?: boolean,
) => Promise<T>

export function createRequester({ fetchFn, onUnauthorized }: ApiOptions = {}): Requester {
  return async function request<T>(
    method: string,
    path: string,
    body?: unknown,
    isLogin = false,
  ): Promise<T> {
    const doFetch = fetchFn ?? ((input, init) => globalThis.fetch(input, init))
    let response: Response
    try {
      response = await doFetch(`${API_BASE}${path}`, {
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
}

/** Строка запроса из заданных параметров; пустые значения пропускаются. */
export function query(params: Record<string, string | undefined>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value) search.set(key, value)
  }
  const text = search.toString()
  return text ? `?${text}` : ''
}
