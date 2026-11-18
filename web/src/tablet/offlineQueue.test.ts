import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { ApiError, NetworkError } from './api.ts'
import type { ResultSubmission } from './api.ts'
import { classifyFailure, createOfflineQueue, memoryStore } from './offlineQueue.ts'
import type { SendOutcome } from './offlineQueue.ts'

function payload(id: string): ResultSubmission {
  return {
    session_id: id,
    discipline: 'darts',
    section: 'physical',
    finished_at: '2027-04-12T07:05:00.000Z',
    entries: [{ participant_code: 'NT07', outcome: 'completed', points: 10 }],
  }
}

function fakeSend(...outcomes: SendOutcome[]) {
  const sent: string[] = []
  const send = vi.fn((p: ResultSubmission): Promise<SendOutcome> => {
    sent.push(p.session_id)
    return Promise.resolve(outcomes.shift() ?? { kind: 'sent' })
  })
  return { send, sent }
}

describe('offline queue', () => {
  test('enqueue keeps the payload in the store and counts it', async () => {
    const store = memoryStore()
    const queue = createOfflineQueue(store, fakeSend().send)
    await queue.enqueue(payload('a'))
    expect(queue.getSnapshot().pending).toHaveLength(1)
    expect((await store.list())[0]?.payload.session_id).toBe('a')
  })

  test('success removes the item from queue and store', async () => {
    const store = memoryStore()
    const { send, sent } = fakeSend()
    const queue = createOfflineQueue(store, send)
    await queue.enqueue(payload('a'))
    await queue.flush()
    expect(sent).toEqual(['a'])
    expect(queue.getSnapshot().pending).toHaveLength(0)
    expect(await store.list()).toEqual([])
  })

  test('network failure keeps the item and stops at the first retry', async () => {
    const store = memoryStore()
    const { send, sent } = fakeSend({ kind: 'retry' })
    const queue = createOfflineQueue(store, send)
    await queue.enqueue(payload('a'))
    await queue.enqueue(payload('b'))
    await queue.flush()
    expect(sent).toEqual(['a'])
    expect(queue.getSnapshot().pending).toHaveLength(2)
    await queue.flush()
    expect(sent).toEqual(['a', 'a', 'b'])
    expect(queue.getSnapshot().pending).toHaveLength(0)
  })

  test('rejected item moves to errors with its message and is not retried', async () => {
    const store = memoryStore()
    const { send, sent } = fakeSend({ kind: 'rejected', message: 'Конфликт' })
    const queue = createOfflineQueue(store, send)
    await queue.enqueue(payload('a'))
    await queue.flush()
    const snapshot = queue.getSnapshot()
    expect(snapshot.pending).toHaveLength(0)
    expect(snapshot.failed.map((i) => [i.sessionId, i.error])).toEqual([['a', 'Конфликт']])
    expect((await store.list())[0]?.state).toBe('failed')
    await queue.flush()
    expect(sent).toEqual(['a'])
  })

  test('dismiss removes a failed item', async () => {
    const store = memoryStore()
    const queue = createOfflineQueue(store, fakeSend().send)
    await queue.reject(payload('a'), 'Ошибка')
    await queue.dismiss('a')
    expect(queue.getSnapshot().failed).toHaveLength(0)
    expect(await store.list()).toEqual([])
  })

  test('a new queue picks up items left in the store', async () => {
    const store = memoryStore()
    await createOfflineQueue(store, fakeSend().send).enqueue(payload('a'))
    const { send, sent } = fakeSend()
    const queue = createOfflineQueue(store, send)
    await queue.flush()
    expect(sent).toEqual(['a'])
  })

  test('the same session_id is stored once', async () => {
    const queue = createOfflineQueue(memoryStore(), fakeSend().send)
    await queue.enqueue(payload('a'))
    await queue.enqueue(payload('a'))
    expect(queue.getSnapshot().pending).toHaveLength(1)
  })

  test('notifies subscribers until they unsubscribe', async () => {
    const queue = createOfflineQueue(memoryStore(), fakeSend().send)
    const listener = vi.fn()
    const unsubscribe = queue.subscribe(listener)
    await queue.enqueue(payload('a'))
    expect(listener).toHaveBeenCalled()
    unsubscribe()
    listener.mockClear()
    await queue.flush()
    expect(listener).not.toHaveBeenCalled()
  })
})

describe('offline queue retry loop', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  test('retries every 5 s and on the online event, stops after stop()', async () => {
    const { send, sent } = fakeSend({ kind: 'retry' }, { kind: 'retry' })
    const queue = createOfflineQueue(memoryStore(), send)
    await queue.enqueue(payload('a'))
    const stop = queue.start()
    await vi.advanceTimersByTimeAsync(0)
    expect(sent).toEqual(['a'])
    await vi.advanceTimersByTimeAsync(4999)
    expect(sent).toEqual(['a'])
    await vi.advanceTimersByTimeAsync(1)
    expect(sent).toEqual(['a', 'a'])
    window.dispatchEvent(new Event('online'))
    await vi.advanceTimersByTimeAsync(0)
    expect(sent).toEqual(['a', 'a', 'a'])
    expect(queue.getSnapshot().pending).toHaveLength(0)
    stop()
    await queue.enqueue(payload('b'))
    await vi.advanceTimersByTimeAsync(20000)
    expect(sent).not.toContain('b')
  })
})

describe('classifyFailure', () => {
  test.each([409, 422, 403, 400])('status %i is a rejection', (status) => {
    expect(classifyFailure(new ApiError(status, 'x', 'T')).kind).toBe('rejected')
  })

  test.each([401, 500, 503])('status %i is retried', (status) => {
    expect(classifyFailure(new ApiError(status, 'x', 'T')).kind).toBe('retry')
  })

  test('network error is retried', () => {
    expect(classifyFailure(new NetworkError()).kind).toBe('retry')
  })
})
