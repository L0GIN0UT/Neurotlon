import { ApiError } from './api.ts'
import type { Api, ResultSubmission } from './api.ts'
import { errorText } from './messages.ts'

export const RETRY_INTERVAL_MS = 5000

export interface QueueItem {
  sessionId: string
  payload: ResultSubmission
  queuedAt: string
  state: 'pending' | 'failed'
  /** Чья запись: отправлять её может только тот же волонтёр. */
  login?: string
  /** Текст ошибки сервера для состояния failed. */
  error?: string
}

/** Хранилище очереди: IndexedDB в браузере, память в тестах. */
export interface QueueStore {
  list(): Promise<QueueItem[]>
  put(item: QueueItem): Promise<void>
  remove(sessionId: string): Promise<void>
}

export type SendOutcome =
  | { kind: 'sent' }
  | { kind: 'rejected'; message: string }
  | { kind: 'retry' }

export interface QueueSnapshot {
  /** Записи текущего волонтёра, ждущие отправки. */
  pending: readonly QueueItem[]
  /** Записи текущего волонтёра, отклонённые сервером. */
  failed: readonly QueueItem[]
  /** Записи другого логина: не отправляются и не показываются как свои. */
  foreign: readonly QueueItem[]
}

/** Хранилище не приняло запись (например, нет места): результат не сохранён. */
export class QueueSaveError extends Error {
  constructor() {
    super('queue save failed')
    this.name = 'QueueSaveError'
  }
}

export function memoryStore(): QueueStore {
  const items = new Map<string, QueueItem>()
  return {
    list: () => Promise.resolve([...items.values()]),
    put: (item) => {
      items.set(item.sessionId, item)
      return Promise.resolve()
    },
    remove: (sessionId) => {
      items.delete(sessionId)
      return Promise.resolve()
    },
  }
}

export type FailureOutcome = Exclude<SendOutcome, { kind: 'sent' }>

/** Сеть, 401 и 5xx — повторить позже; остальные ошибки сервера (409, 422 …) — отказ. */
export function classifyFailure(error: unknown): FailureOutcome {
  if (error instanceof ApiError && error.status !== 401 && error.status < 500) {
    return { kind: 'rejected', message: errorText(error) }
  }
  return { kind: 'retry' }
}

/** 200/201 — отправлено, иначе см. classifyFailure. */
export function makeSender(api: Pick<Api, 'submitResult'>) {
  return async (payload: ResultSubmission): Promise<SendOutcome> => {
    try {
      await api.submitResult(payload)
      return { kind: 'sent' }
    } catch (error) {
      return classifyFailure(error)
    }
  }
}

export function createOfflineQueue(
  store: QueueStore,
  send: (payload: ResultSubmission) => Promise<SendOutcome>,
  now: () => Date = () => new Date(),
) {
  const items = new Map<string, QueueItem>()
  const listeners = new Set<() => void>()
  let loaded: Promise<void> | null = null
  let flushing = false
  let currentLogin: string | null = null
  let snapshot: QueueSnapshot = { pending: [], failed: [], foreign: [] }

  function publish() {
    const all = [...items.values()]
    const mine = all.filter((i) => i.login === currentLogin)
    snapshot = {
      pending: mine.filter((i) => i.state === 'pending'),
      failed: mine.filter((i) => i.state === 'failed'),
      foreign: all.filter((i) => i.login !== currentLogin),
    }
    listeners.forEach((listener) => listener())
  }

  function load(): Promise<void> {
    loaded ??= store.list().then((stored) => {
      for (const item of stored) if (!items.has(item.sessionId)) items.set(item.sessionId, item)
      publish()
    })
    return loaded
  }

  async function save(item: QueueItem) {
    const previous = items.get(item.sessionId)
    items.set(item.sessionId, item)
    publish()
    try {
      await store.put(item)
    } catch {
      // не оставляем в памяти запись, которой нет в хранилище
      if (previous) items.set(item.sessionId, previous)
      else items.delete(item.sessionId)
      publish()
      throw new QueueSaveError()
    }
  }

  /** Отправляет накопленное по порядку; на первой сетевой ошибке останавливается. */
  async function flush() {
    await load()
    if (flushing) return
    flushing = true
    try {
      for (const item of [...snapshot.pending]) {
        const outcome = await send(item.payload)
        if (outcome.kind === 'retry') break
        if (outcome.kind === 'sent') {
          items.delete(item.sessionId)
          publish()
          await store.remove(item.sessionId)
        } else {
          await save({ ...item, state: 'failed', error: outcome.message }).catch(() => undefined)
        }
      }
    } finally {
      flushing = false
    }
  }

  return {
    flush,
    /** Логин вошедшего волонтёра; null — никто не вошёл, ничего не отправляется. */
    setLogin(login: string | null) {
      currentLogin = login
      publish()
    },
    getSnapshot: () => snapshot,
    subscribe(listener: () => void) {
      listeners.add(listener)
      return () => {
        listeners.delete(listener)
      }
    },
    load,
    async enqueue(payload: ResultSubmission) {
      await load()
      await save({
        sessionId: payload.session_id,
        payload,
        queuedAt: now().toISOString(),
        state: 'pending',
        ...(currentLogin === null ? {} : { login: currentLogin }),
      })
    },
    /** Результат, отклонённый сервером при прямой отправке. */
    async reject(payload: ResultSubmission, message: string) {
      await load()
      await save({
        sessionId: payload.session_id,
        payload,
        queuedAt: now().toISOString(),
        state: 'failed',
        error: message,
        ...(currentLogin === null ? {} : { login: currentLogin }),
      })
    },
    async dismiss(sessionId: string) {
      await load()
      items.delete(sessionId)
      publish()
      await store.remove(sessionId)
    },
    /** Повтор каждые intervalMs и при событии online; возвращает функцию остановки. */
    start(intervalMs: number = RETRY_INTERVAL_MS) {
      const tick = () => {
        void flush()
      }
      tick()
      const timer = setInterval(tick, intervalMs)
      window.addEventListener('online', tick)
      return () => {
        clearInterval(timer)
        window.removeEventListener('online', tick)
      }
    },
  }
}

export type OfflineQueue = ReturnType<typeof createOfflineQueue>
