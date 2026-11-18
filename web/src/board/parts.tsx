import { formatPoints } from './format.ts'
import { teamPoints, teamStyle } from './model.ts'
import type { BoardTeam, BoardTop } from './useScoreboard.ts'

export function Top({ rows, side }: { rows: BoardTop[]; side: 'a' | 'b' }) {
  return (
    <ol className={`top side-${side}`}>
      {rows.map((row) => (
        <li
          key={row.rank ?? `pending-${row.number}`}
          className={row.pending ? 'player pending' : 'player'}
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
