import { BadgesApp } from './badges/BadgesApp.tsx'
import { BoardApp } from './board/BoardApp.tsx'
import { OverlayApp } from './board/OverlayApp.tsx'
import { AdminApp } from './staff/AdminApp.tsx'
import { JudgeApp } from './staff/JudgeApp.tsx'
import { matches } from './routes.ts'
import { TabletApp } from './tablet/TabletApp.tsx'

const ROUTES: { path: string; label: string }[] = [
  { path: '/tablet', label: 'Планшет волонтёра' },
  { path: '/admin', label: 'Админка' },
  { path: '/judge', label: 'Результаты' },
  { path: '/board', label: 'Табло' },
]

export function App() {
  // Страниц мало, вкладки внутри страниц — состояние, поэтому роутер не нужен:
  // сервер отдаёт index.html для каждого из этих путей (/overlay — для OBS, в списке ссылок его нет).
  const { pathname } = window.location
  if (matches(pathname, '/tablet')) return <TabletApp />
  if (matches(pathname, '/admin')) return <AdminApp />
  if (matches(pathname, '/badges')) return <BadgesApp />
  if (matches(pathname, '/judge')) return <JudgeApp />
  if (matches(pathname, '/board')) return <BoardApp />
  if (matches(pathname, '/overlay')) return <OverlayApp />
  return (
    <>
      <h1>Нейротлон</h1>
      <ul>
        {ROUTES.map((route) => (
          <li key={route.path}>
            <a
              href={route.path}
              {...(route.path === '/board' ? { target: '_blank', rel: 'noopener noreferrer' } : {})}
            >
              {route.label}
            </a>
          </li>
        ))}
      </ul>
    </>
  )
}
