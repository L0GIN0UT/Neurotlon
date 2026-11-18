import type { BoardTeam, BoardTop, Scoreboard } from './useScoreboard.ts'

export function team(
  number: number,
  name: string,
  color: string,
  top: Partial<Record<string, BoardTop[]>> = {},
  extra: Partial<BoardTeam> = {},
): BoardTeam {
  return {
    rank: number,
    number,
    name,
    color,
    total: 0,
    duel_score: 0,
    by_discipline: { darts: 0, football: 0, pong: 0 },
    sections_passed: 0,
    finished: false,
    top: { darts: [], football: [], pong: [], ...top },
    ...extra,
  }
}

export function rows(prefix: string, n: number, base = 10): BoardTop[] {
  return Array.from({ length: n }, (_, i) => ({
    rank: i + 1,
    number: i + 1,
    label: `${prefix}${i + 1}`,
    points: base - i,
    pending: false,
  }))
}

export const snapshot: Scoreboard = {
  teams: [
    team(
      1,
      'Красные',
      '#e6194b',
      {
        darts: [
          { rank: 1, number: 2, label: 'Аня', points: 80, pending: false },
          { rank: null, number: 1, label: 'NT02', points: 0, pending: true },
        ],
        pong: [{ rank: 1, number: 3, label: 'Вера', points: 10, pending: false }],
      },
      { duel_score: 2, by_discipline: { darts: 80, football: 40.5, pong: 10 } },
    ),
    team(
      2,
      'Синие',
      '#4363d8',
      { darts: [{ rank: 1, number: 1, label: 'Боря', points: 15, pending: false }] },
      { duel_score: 1, by_discipline: { darts: 15, football: 0, pong: 20 } },
    ),
  ],
}
