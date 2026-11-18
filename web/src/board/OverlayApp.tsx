import { useEffect } from 'react'
import type { CSSProperties } from 'react'
import { DisciplineIcon } from '../shared/icons/DisciplineIcon.tsx'
import { BOARD_DISCIPLINES, disciplineName, duelTeams, teamStyle } from './model.ts'
import { OVERLAY_TOP, parseScale, parseView } from './overlayParams.ts'
import { Top, Versus } from './parts.tsx'
import { useScoreboard } from './useScoreboard.ts'
import type { SourceFactory } from './useScoreboard.ts'
import './board.css'

interface Props {
  createSource?: SourceFactory
  /** Строка запроса страницы; по умолчанию `window.location.search`. */
  search?: string
}

/** Оверлей для OBS (Browser source): прозрачный фон, без входа, тот же поток SSE, что и табло. */
export function OverlayApp({ createSource, search = window.location.search }: Props) {
  const { board } = useScoreboard(createSource)
  const view = parseView(search)
  const scale = parseScale(search)

  // OBS рисует страницу поверх видео: фон html, body и #root должен быть прозрачным.
  useEffect(() => {
    const targets = [document.documentElement, document.body, document.getElementById('root')]
    const saved = targets.map((el) => el?.style.backgroundColor ?? '')
    for (const el of targets) if (el) el.style.backgroundColor = 'transparent'
    document.body.classList.add('overlay-body')
    return () => {
      targets.forEach((el, i) => {
        if (el) el.style.backgroundColor = saved[i] ?? ''
      })
      document.body.classList.remove('overlay-body')
    }
  }, [])

  const [a, b] = duelTeams(board)
  if (a === undefined) return <main className="overlay" data-view={view} />
  return (
    <main
      className="overlay"
      data-view={view}
      style={{ '--scale': scale } as CSSProperties}
      aria-label="Оверлей табло"
    >
      <header className="duel plate" aria-label="Счёт дуэли">
        <h2 className="team-name name-a" style={teamStyle(a)}>
          {a.name}
        </h2>
        <span className="duel-score score-a" style={teamStyle(a)} aria-label="Победы команды A">
          {a.duel_score}
        </span>
        <span className="vs">VS</span>
        <span className="duel-score score-b" style={teamStyle(b)} aria-label="Победы команды B">
          {b?.duel_score ?? 0}
        </span>
        <h2 className="team-name name-b" style={teamStyle(b)}>
          {b?.name ?? ''}
        </h2>
      </header>
      <div className="rows plate">
        {BOARD_DISCIPLINES.map((code) => (
          <section
            key={code}
            className="row"
            aria-label={disciplineName(code)}
            data-discipline={code}
          >
            {view === 'full' ? (
              <Top rows={(a.top[code] ?? []).slice(0, OVERLAY_TOP)} side="a" />
            ) : (
              <span />
            )}
            <div className="mid">
              <span className="icon">
                <DisciplineIcon discipline={code} />
              </span>
              <Versus a={a} b={b} discipline={code} />
            </div>
            {view === 'full' ? (
              <Top rows={(b?.top[code] ?? []).slice(0, OVERLAY_TOP)} side="b" />
            ) : (
              <span />
            )}
          </section>
        ))}
      </div>
    </main>
  )
}
