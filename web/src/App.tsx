import { TabletApp } from './tablet/TabletApp.tsx'

export function App() {
  // Маршрутов мало: пока достаточно сравнить путь.
  if (window.location.pathname.startsWith('/tablet')) return <TabletApp />
  return (
    <>
      <h1>Нейротлон</h1>
      <p>
        <a href="/tablet">Планшет волонтёра</a>
      </p>
    </>
  )
}
