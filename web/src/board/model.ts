import type { CSSProperties } from 'react'
import { DISCIPLINE_NAMES } from '../shared/messages.ts'
import type { Discipline } from '../shared/types.ts'
import type { BoardTeam, Scoreboard } from './useScoreboard.ts'

/** Порядок полос на табло и строк в оверлее. */
export const BOARD_DISCIPLINES = ['darts', 'football', 'pong'] as const

/** Команды A и B: первые две по номеру (жеребьёвка делит команды на дуэли попарно). */
export function duelTeams(board: Scoreboard | null): [BoardTeam | undefined, BoardTeam | undefined] {
  const sorted = [...(board?.teams ?? [])].sort((a, b) => a.number - b.number)
  return [sorted[0], sorted[1]]
}

export function teamPoints(team: BoardTeam | undefined, discipline: string): number {
  return team?.by_discipline[discipline] ?? 0
}

export function disciplineName(code: string): string {
  return DISCIPLINE_NAMES[code as Discipline] ?? code
}

export function teamStyle(team: BoardTeam | undefined): CSSProperties {
  return { '--team': team?.color ?? '#ffffff' } as CSSProperties
}
