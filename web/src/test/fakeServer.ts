import { vi } from 'vitest'

export type Handler = (body: unknown, url: URL) => Response | Promise<Response>

export function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

export function problem(status: number, code: string): Response {
  return json({ type: 'about:blank', title: code, status, code }, status)
}

export interface FakeServer {
  fetchFn: typeof fetch
  /** Ключ — «МЕТОД /путь» без /api/v1; `*` заменяет один сегмент пути. */
  routes: Map<string, Handler>
  calls: { key: string; body: unknown; url: URL; contentType: string | null }[]
  bodies: (key: string) => unknown[]
  count: (key: string) => number
}

function resolveKey(routes: Map<string, Handler>, exact: string): string {
  if (routes.has(exact)) return exact
  for (const key of routes.keys()) {
    if (!key.includes('*')) continue
    const pattern = key.replace(/[.+?^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '[^/]+')
    if (new RegExp(`^${pattern}$`).test(exact)) return key
  }
  return exact
}

/** fetch для тестов: по таблице маршрутов; неизвестный маршрут — 404. */
export function createFakeServer(role: string | null, login = 'boss'): FakeServer {
  const routes = new Map<string, Handler>()
  const calls: FakeServer['calls'] = []
  let loggedIn = role !== null
  routes.set('POST /auth/login', () => {
    loggedIn = true
    return new Response(null, { status: 204 })
  })
  routes.set('POST /auth/logout', () => {
    loggedIn = false
    return new Response(null, { status: 204 })
  })
  routes.set('GET /auth/me', () =>
    loggedIn ? json({ login, role: role ?? 'admin', discipline: null }) : problem(401, 'unauthorized'),
  )

  const fetchFn = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'https://hall.local')
    const path = url.pathname.replace('/api/v1', '')
    const method = init?.method ?? 'GET'
    // Blob (JPEG фото) остаётся как есть, остальное тело — JSON
    const body: unknown =
      init?.body instanceof Blob ? init.body : init?.body ? JSON.parse(String(init.body)) : undefined
    const key = resolveKey(routes, `${method} ${path}`)
    calls.push({ key, body, url, contentType: new Headers(init?.headers).get('Content-Type') })
    const handler = routes.get(key)
    if (!handler) return Promise.resolve(problem(404, 'not_found'))
    return Promise.resolve(handler(body, url))
  }) as unknown as typeof fetch

  return {
    fetchFn,
    routes,
    calls,
    bodies: (key) => calls.filter((c) => c.key === key).map((c) => c.body),
    count: (key) => calls.filter((c) => c.key === key).length,
  }
}

/** Подмена EventSource: тест сам шлёт события и ошибки. */
export class FakeEventSource {
  static instances: FakeEventSource[] = []
  readyState = 0
  onerror: ((event: Event) => void) | null = null
  closed = false
  private listeners = new Map<string, ((event: MessageEvent<string>) => void)[]>()

  readonly url: string

  constructor(url: string) {
    this.url = url
    FakeEventSource.instances.push(this)
  }

  addEventListener(type: string, listener: (event: MessageEvent<string>) => void) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener])
  }

  close() {
    this.closed = true
    this.readyState = 2
  }

  emit(type: string, data: unknown) {
    this.readyState = 1
    const event = new MessageEvent(type, { data: JSON.stringify(data) })
    for (const listener of this.listeners.get(type) ?? []) listener(event)
  }

  /** Браузер закрыл поток после ответа с ошибкой (readyState = CLOSED). */
  failClosed() {
    this.readyState = 2
    this.onerror?.(new Event('error'))
  }

  /** Обрыв: браузер сам переподключится (readyState = CONNECTING). */
  failReconnecting() {
    this.readyState = 0
    this.onerror?.(new Event('error'))
  }

  static reset() {
    FakeEventSource.instances = []
  }
}
