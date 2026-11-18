import { useCallback, useEffect, useRef, useState } from 'react'

interface Loader<T> {
  data: T | undefined
  error: unknown
  reload: () => void
}

/** Загружает данные при открытии вкладки; `intervalMs` включает периодическое обновление. */
export function useLoader<T>(load: () => Promise<T>, intervalMs?: number): Loader<T> {
  const [data, setData] = useState<T>()
  const [error, setError] = useState<unknown>(null)
  const loadRef = useRef(load)
  useEffect(() => {
    loadRef.current = load
  })
  const alive = useRef(true)

  const reload = useCallback(() => {
    loadRef.current().then(
      (value) => {
        if (!alive.current) return
        setData(value)
        setError(null)
      },
      (e: unknown) => {
        if (alive.current) setError(e)
      },
    )
  }, [])

  useEffect(() => {
    alive.current = true
    reload()
    const timer = intervalMs === undefined ? undefined : setInterval(reload, intervalMs)
    return () => {
      alive.current = false
      if (timer !== undefined) clearInterval(timer)
    }
  }, [reload, intervalMs])

  return { data, error, reload }
}

/** Выполняет действие с состоянием «занято» и текстом ошибки. */
export function useAction() {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const run = useCallback(async <T,>(action: () => Promise<T>): Promise<T | undefined> => {
    setBusy(true)
    setError(null)
    try {
      return await action()
    } catch (e) {
      setError(e)
      return undefined
    } finally {
      setBusy(false)
    }
  }, [])
  return { busy, error, run, clear: () => setError(null) }
}
