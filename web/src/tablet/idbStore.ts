import { memoryStore } from './offlineQueue.ts'
import type { QueueItem, QueueStore } from './offlineQueue.ts'

const DB_NAME = 'neurotlon-tablet'
const STORE = 'queue'

function request<T>(req: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => reject(req.error)
  })
}

/** Очередь результатов в IndexedDB; без IndexedDB — в памяти. */
export function createIdbStore(): QueueStore {
  if (typeof indexedDB === 'undefined') return memoryStore()
  let opened: Promise<IDBDatabase> | null = null
  function open(): Promise<IDBDatabase> {
    opened ??= new Promise((resolve, reject) => {
      const req = indexedDB.open(DB_NAME, 1)
      req.onupgradeneeded = () => {
        req.result.createObjectStore(STORE, { keyPath: 'sessionId' })
      }
      req.onsuccess = () => resolve(req.result)
      req.onerror = () => reject(req.error)
    })
    return opened
  }
  async function objectStore(mode: IDBTransactionMode) {
    return (await open()).transaction(STORE, mode).objectStore(STORE)
  }
  return {
    list: async () => request<QueueItem[]>((await objectStore('readonly')).getAll()),
    put: async (item) => {
      await request((await objectStore('readwrite')).put(item))
    },
    remove: async (sessionId) => {
      await request((await objectStore('readwrite')).delete(sessionId))
    },
  }
}
