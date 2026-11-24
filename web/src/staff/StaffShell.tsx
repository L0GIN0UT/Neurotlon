import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { createPortal } from 'react-dom'
import logo from '../station/assets/logo.png'
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

/** Место в боковой панели, куда `Tabs` выводит меню разделов. */
const MenuContext = createContext<{ node: HTMLElement | null; onPick: () => void }>({
  node: null,
  onPick: () => undefined,
})

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

  const [menuNode, setMenuNode] = useState<HTMLElement | null>(null)
  // На узких экранах панель — верхняя полоса, разделы раскрываются кнопкой «Меню».
  const [menuOpen, setMenuOpen] = useState(false)
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

  const ready = auth.status === 'ready' ? auth : null
  const here = window.location.pathname
  const pages = [
    ...(ready && ready.me.role !== 'judge' ? [{ href: '/admin', label: 'Админка' }] : []),
    { href: '/judge', label: 'Судья' },
    { href: '/board', label: 'Табло' },
  ]
  return (
    <main className="staff">
      {!ready && (
        <div className="staff-center">
          {auth.status === 'loading' && <p className="card">Загрузка…</p>}
          {auth.status === 'anon' && (
            <Login api={api} onLoggedIn={resolve} title={`Вход: ${title}`} />
          )}
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
        </div>
      )}
      {ready && (
        <>
          <aside className={`staff-side no-print${menuOpen ? ' open' : ''}`}>
            <div className="staff-brand">
              <img src={logo} alt="" />
              <strong>{title}</strong>
            </div>
            <button
              type="button"
              className="staff-toggle"
              aria-expanded={menuOpen}
              aria-controls="staff-nav"
              onClick={() => setMenuOpen(!menuOpen)}
            >
              Меню
            </button>
            <div id="staff-nav" className="staff-nav">
              <nav className="staff-menu" ref={setMenuNode} aria-label="Разделы" />
              <nav className="staff-pages" aria-label="Страницы">
                {pages.map((page) => (
                  <a
                    key={page.href}
                    href={page.href}
                    aria-current={here.startsWith(page.href) ? 'page' : undefined}
                    // Табло показывают на отдельном экране: всегда в новой вкладке, рабочая страница остаётся.
                    {...(page.href === '/board' ? { target: '_blank', rel: 'noopener noreferrer' } : {})}
                  >
                    {page.label}
                  </a>
                ))}
              </nav>
            </div>
            <div className="staff-user">
              <span>{ready.me.login}</span>
              <button type="button" className="small" onClick={() => void logout()}>
                Выйти
              </button>
            </div>
          </aside>
          <div className="staff-main">
            <MenuContext.Provider value={{ node: menuNode, onPick: () => setMenuOpen(false) }}>
              {children({ api, me: ready.me })}
            </MenuContext.Provider>
          </div>
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
  const { node: menu, onPick } = useContext(MenuContext)
  const list = (
    <div role="tablist" aria-orientation="vertical" className="tabs no-print">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          type="button"
          role="tab"
          aria-selected={tab.id === active}
          className={tab.id === active ? 'on' : ''}
          onClick={() => {
            onChange(tab.id)
            onPick()
          }}
        >
          {tab.label}
        </button>
      ))}
    </div>
  )
  // В боковой панели; пока панель не готова (первый кадр), меню не рисуем.
  return menu ? createPortal(list, menu) : null
}

/** Заголовок раздела: что это и зачем. */
export function PageHead({
  title,
  hint,
  children,
}: {
  title: string
  hint?: string
  children?: ReactNode
}) {
  return (
    <header className="page-head">
      <div>
        <h1>{title}</h1>
        {hint && <p>{hint}</p>}
      </div>
      {children && <div className="row no-print">{children}</div>}
    </header>
  )
}
