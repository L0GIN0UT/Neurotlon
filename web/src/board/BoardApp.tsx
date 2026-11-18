import { useEffect } from 'react'
import type { CSSProperties } from 'react'
import { DISCIPLINE_NAMES } from '../shared/messages.ts'
import type { Discipline } from '../shared/types.ts'
import { formatPoints, textOn } from './format.ts'
import { useScoreboard } from './useScoreboard.ts'
import type { BoardMember, BoardTeam, SourceFactory } from './useScoreboard.ts'
import './board.css'

const DEFAULT_SECTIONS = 6 // 3 дисциплины × (BCI + физическая)

function disciplineName(code: string): string {
  return DISCIPLINE_NAMES[code as Discipline] ?? code
}

function Member({ member, sections }: { member: BoardMember; sections: number }) {
  return (
    <li className={member.pending ? 'member pending' : 'member'}>
      <span className="label">{member.label}</span>
      {member.pending && <span className="flag">нужно решение</span>}
      <span className="passed">
        {member.sections_passed}/{sections}
      </span>
      <span className="points">{formatPoints(member.total)}</span>
    </li>
  )
}

function Team({ team }: { team: BoardTeam }) {
  const sections = Object.keys(team.by_discipline).length * 2 || DEFAULT_SECTIONS
  return (
    <section
      className="team"
      aria-label={team.name}
      style={
        {
          '--team': team.color,
          '--on-team': textOn(team.color),
          '--rows': Math.max(team.members.length, 1),
        } as CSSProperties
      }
    >
      <header>
        <span className="rank">{team.rank}</span>
        <h2>{team.name}</h2>
        <span className="total">{formatPoints(team.total)}</span>
      </header>
      <ul className="disciplines">
        {Object.entries(team.by_discipline).map(([code, points]) => (
          <li key={code}>
            <span>{disciplineName(code)}</span>
            <strong>{formatPoints(points)}</strong>
          </li>
        ))}
      </ul>
      <ul className="members">
        {team.members.map((member) => (
          <Member key={member.label} member={member} sections={sections} />
        ))}
      </ul>
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

  const teams = board?.teams ?? []
  return (
    <main
      className="board"
      onDoubleClick={() => void document.documentElement.requestFullscreen?.()}
    >
      {board === null && <p className="empty">Подключаемся к табло…</p>}
      {board !== null && teams.length === 0 && <p className="empty">Ждём жеребьёвки</p>}
      <div className="teams" style={{ '--count': Math.max(teams.length, 1) } as CSSProperties}>
        {teams.map((team) => (
          <Team key={team.number} team={team} />
        ))}
      </div>
      {connection === 'offline' && (
        <p className="status" role="status">
          Нет связи с сервером, показаны последние данные
        </p>
      )}
    </main>
  )
}
