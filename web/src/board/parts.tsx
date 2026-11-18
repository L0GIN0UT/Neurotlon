import { formatPoints } from './format.ts'
import type { CSSProperties } from 'react'
import { barPercent, teamPoints, teamStyle } from './model.ts'
import type { BoardTeam, BoardTop } from './useScoreboard.ts'

export function Top({
  rows,
  side,
  team,
  max = 0,
}: {
  rows: BoardTop[]
  side: 'a' | 'b'
  team?: BoardTeam
  /** Наибольшие очки в полосе: от них считается длина шкалы. 0 — без шкалы. */
  max?: number
}) {
  return (
    <ol className={`top side-${side}`} style={teamStyle(team)}>
      {rows.map((row) => (
        <li
          key={row.rank ?? `pending-${row.number}`}
          className={['player', row.pending && 'pending', row.rank === 1 && 'leader']
            .filter(Boolean)
            .join(' ')}
          style={{ '--fill': `${barPercent(row.points, max)}%` } as CSSProperties}
        >
          <span className="place">{row.rank ?? ''}</span>
          <span className="label">{row.label}</span>
          {row.pending && <span className="flag">нужно решение</span>}
          <span className="points">{formatPoints(row.points)}</span>
        </li>
      ))}
    </ol>
  )
}

export function Versus({
  a,
  b,
  discipline,
}: {
  a: BoardTeam | undefined
  b: BoardTeam | undefined
  discipline: string
}) {
  return (
    <span className="versus">
      <b className="score-a" style={teamStyle(a)}>
        {formatPoints(teamPoints(a, discipline))}
      </b>
      <i>vs</i>
      <b className="score-b" style={teamStyle(b)}>
        {formatPoints(teamPoints(b, discipline))}
      </b>
    </span>
  )
}
