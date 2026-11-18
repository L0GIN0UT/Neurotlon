import { useEffect } from 'react'
import { DisciplineIcon } from './icons.tsx'
import { BOARD_DISCIPLINES, disciplineName, duelTeams, teamStyle } from './model.ts'
import { Top, Versus } from './parts.tsx'
import { useScoreboard } from './useScoreboard.ts'
import type { BoardTeam, SourceFactory } from './useScoreboard.ts'
import './board.css'

function Band({
  discipline,
  a,
  b,
}: {
  discipline: string
  a: BoardTeam | undefined
  b: BoardTeam | undefined
}) {
  const name = disciplineName(discipline)
  return (
    <section className="band" aria-label={name} data-discipline={discipline}>
      <Top rows={a?.top[discipline] ?? []} side="a" />
      <div className="centre">
        <span className="icon">
          <DisciplineIcon discipline={discipline} />
        </span>
        <span className="band-name">{name}</span>
        <Versus a={a} b={b} discipline={discipline} />
      </div>
      <Top rows={b?.top[discipline] ?? []} side="b" />
    </section>
  )
}

interface Props {
  createSource?: SourceFactory
}

/** Табло для большого экрана: без входа, без прокрутки, обновляется по SSE. */
export function BoardApp({ createSource }: Props) {
  const { board, connection } = useScoreboard(createSource)

  useEffect(() => {
    document.body.classList.add('board-body')
    return () => document.body.classList.remove('board-body')
  }, [])

  const [a, b] = duelTeams(board)
  return (
    <main
      className="board"
      onDoubleClick={() => void document.documentElement.requestFullscreen?.()}
    >
      {board === null && <p className="empty">Подключаемся к табло…</p>}
      {board !== null && a === undefined && <p className="empty">Ждём жеребьёвки</p>}
      {a !== undefined && (
        <>
          <header className="duel" aria-label="Счёт дуэли">
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
          <div className="bands">
            {BOARD_DISCIPLINES.map((code) => (
              <Band key={code} discipline={code} a={a} b={b} />
            ))}
          </div>
        </>
      )}
      {connection === 'offline' && (
        <p className="status" role="status">
          Нет связи с сервером, показаны последние данные
        </p>
      )}
    </main>
  )
}
