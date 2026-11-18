import type { DisciplineConfig, Me } from './api.ts'

// Копия профиля и настроек секции: нужна, чтобы планшет работал после перезагрузки без связи.
const KEY = 'neurotlon.tablet.cache.v1'

interface Cached {
  me?: Me
  config?: DisciplineConfig
}

function read(): Cached {
  try {
    return JSON.parse(localStorage.getItem(KEY) ?? '{}') as Cached
  } catch {
    return {}
  }
}

export function loadCached(): Cached {
  return read()
}

export function saveCached(patch: Cached): void {
  try {
    localStorage.setItem(KEY, JSON.stringify({ ...read(), ...patch }))
  } catch {
    // хранилище недоступно — работаем без копии
  }
}

export function clearCached(): void {
  try {
    localStorage.removeItem(KEY)
  } catch {
    // ничего
  }
}
