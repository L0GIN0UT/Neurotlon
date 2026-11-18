import { useCallback, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { ApiError } from '../shared/http.ts'
import { Login } from '../shared/Login.tsx'
import { errorText } from '../shared/messages.ts'
import type { Me, Role } from '../shared/types.ts'
import { createStaffApi } from './api.ts'
import type { StaffApi } from './api.ts'
import './staff.css'

type Auth =
  | { status: 'loading' }
  | { status: 'anon' }
  | { status: 'forbidden'; me: Me }
  | { status: 'error'; message: string }
  | { status: 'ready'; me: Me }

interface Props {
  title: string
  /** Роли, которым открыта страница. */
  allow: Role[]
  fetchFn?: typeof fetch
  children: (ctx: { api: StaffApi; me: Me }) => ReactNode
}

/** Вход, проверка роли и выход для страниц /admin и /judge. */
export function StaffShell({ title, allow, fetchFn, children }: Props) {
  const [auth, setAuth] = useState<Auth>({ status: 'loading' })
  const [api] = useState<StaffApi>(() =>
    createStaffApi({ fetchFn, onUnauthorized: () => setAuth({ status: 'anon' }) }),
  )

  const allowed = allow.join(',')
  const resolve = useCallback(
    (me: Me) => {
      setAuth(allowed.split(',').includes(me.role) ? { status: 'ready', me } : { status: 'forbidden', me })
    },
    [allowed],
  )

  useEffect(() => {
    let active = true
    api.me().then(
      (me) => {
        if (active) resolve(me)
      },
      (e: unknown) => {
        if (!active) return
        if (e instanceof ApiError && e.status === 401) setAuth({ status: 'anon' })
        else setAuth({ status: 'error', message: errorText(e) })
      },
    )
    return () => {
      active = false
    }
  }, [api, resolve])

  async function logout() {
    try {
      await api.logout()
    } catch {
      // сессия всё равно забывается в браузере
    }
    setAuth({ status: 'anon' })
  }

  return (
    <main className="staff">
      {auth.status === 'loading' && <p className="card">Загрузка…</p>}
      {auth.status === 'anon' && <Login api={api} onLoggedIn={resolve} title={`Вход: ${title}`} />}
      {auth.status === 'error' && (
        <section className="card stack">
          <p role="alert" className="error">
            {auth.message}
          </p>
          <button type="button" className="primary" onClick={() => window.location.reload()}>
            Повторить
          </button>
        </section>
      )}
      {auth.status === 'forbidden' && (
        <section className="card stack">
          <h1>Нет доступа</h1>
          <p>Учётная запись «{auth.me.login}» не подходит для этой страницы.</p>
          <button type="button" className="primary" onClick={() => void logout()}>
            Выйти
          </button>
        </section>
      )}
      {auth.status === 'ready' && (
        <>
          <header className="topbar no-print">
            <strong>{title}</strong>
            <nav className="grow">
              {auth.me.role !== 'judge' && <a href="/admin">Админка</a>}
              <a href="/judge">Судья</a>
              <a href="/board">Табло</a>
            </nav>
            <span>{auth.me.login}</span>
            <button type="button" onClick={() => void logout()}>
              Выйти
            </button>
          </header>
          {children({ api, me: auth.me })}
        </>
      )}
    </main>
  )
}

interface TabsProps<T extends string> {
  tabs: { id: T; label: string }[]
  active: T
  onChange: (id: T) => void
}

export function Tabs<T extends string>({ tabs, active, onChange }: TabsProps<T>) {
  return (
    <div role="tablist" className="tabs no-print">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          type="button"
          role="tab"
          aria-selected={tab.id === active}
          className={tab.id === active ? 'on' : ''}
          onClick={() => onChange(tab.id)}
        >
          {tab.label}
        </button>
      ))}
    </div>
  )
}
