// Раскладка участников по областям «не распределены» / команда 1 / команда 2.
// Чистые функции: клиент заранее отбрасывает то, что сервер откажет принять
// (игрок с результатом остаётся на своём месте, дыр в нумерации мест нет).

export type Area = 'pool' | 'team1' | 'team2'

export interface Lineup {
  pool: string[]
  team1: string[]
  team2: string[]
}

export interface Lock {
  area: Area
  index: number
}

export type Locks = ReadonlyMap<string, Lock>

export const TEAM_AREAS: readonly ('team1' | 'team2')[] = ['team1', 'team2']

export function teamNumber(area: 'team1' | 'team2'): 1 | 2 {
  return area === 'team1' ? 1 : 2
}

/** Фиксированных игроков команды расставляет на их места, остальных — по порядку в свободные. */
function settle(candidate: string[], area: Area, locks: Locks): string[] | null {
  const free = candidate.filter((code) => !locks.has(code))
  if (area === 'pool') {
    const lockedHere = [...locks].filter(([, lock]) => lock.area === 'pool').map(([code]) => code)
    return [...free, ...lockedHere].sort()
  }
  const fixed = new Map<number, string>()
  let last = -1
  for (const [code, lock] of locks) {
    if (lock.area !== area) continue
    fixed.set(lock.index, code)
    last = Math.max(last, lock.index)
  }
  const out: string[] = []
  for (let i = 0; free.length > 0 || i <= last; i++) {
    const code = fixed.get(i) ?? free.shift()
    if (code === undefined) return null
    out.push(code)
  }
  return out
}

function sameLineup(a: Lineup, b: Lineup): boolean {
  return (['pool', 'team1', 'team2'] as const).every(
    (area) => a[area].length === b[area].length && a[area].every((code, i) => code === b[area][i]),
  )
}

function finish(current: Lineup, next: Lineup, locks: Locks): Lineup | null {
  const settled: Lineup = { pool: [], team1: [], team2: [] }
  for (const area of ['pool', 'team1', 'team2'] as const) {
    const list = settle(next[area], area, locks)
    if (list === null) return null
    settled[area] = list
  }
  return sameLineup(current, settled) ? null : settled
}

/** Область и место игрока в раскладке. */
export function locate(lineup: Lineup, code: string): { area: Area; index: number } | null {
  for (const area of ['pool', 'team1', 'team2'] as const) {
    const index = lineup[area].indexOf(code)
    if (index >= 0) return { area, index }
  }
  return null
}

/**
 * Переносит игрока в область: `position` — место среди показанных карточек (без него — в конец).
 * Возвращает null, если ход ничего не меняет или сервер его не примет.
 */
export function moveTo(
  lineup: Lineup,
  locks: Locks,
  code: string,
  target: Area,
  position?: number,
): Lineup | null {
  const from = locate(lineup, code)
  if (from === null || locks.has(code)) return null
  const next: Lineup = {
    pool: lineup.pool.filter((c) => c !== code),
    team1: lineup.team1.filter((c) => c !== code),
    team2: lineup.team2.filter((c) => c !== code),
  }
  const shown = next[target]
  // Игрок занимает место цели: вниз внутри команды — после неё, вверх и из другой области — перед ней.
  const at = Math.min(position ?? shown.length, shown.length)
  const freeBefore = shown.slice(0, at).filter((c) => !locks.has(c)).length
  const free = shown.filter((c) => !locks.has(c))
  free.splice(freeBefore, 0, code)
  next[target] = free
  return finish(lineup, next, locks)
}

/** Сдвиг внутри команды на один шаг среди подвижных игроков (фиксированных перешагивает). */
export function step(lineup: Lineup, locks: Locks, code: string, direction: -1 | 1): Lineup | null {
  const from = locate(lineup, code)
  if (from === null || from.area === 'pool' || locks.has(code)) return null
  const free = lineup[from.area].filter((c) => !locks.has(c))
  const i = free.indexOf(code)
  const j = i + direction
  const other = free[j]
  if (other === undefined) return null
  free[i] = other
  free[j] = code
  return finish(lineup, { ...lineup, [from.area]: free }, locks)
}

export interface PairRow {
  k: number
  a: string | null
  b: string | null
}

/** Пара k — k-й игрок команды 1 против k-го игрока команды 2. */
export function pairsOf(lineup: Lineup): PairRow[] {
  const size = Math.max(lineup.team1.length, lineup.team2.length)
  return Array.from({ length: size }, (_, i) => ({
    k: i + 1,
    a: lineup.team1[i] ?? null,
    b: lineup.team2[i] ?? null,
  }))
}

export function assignmentBody(lineup: Lineup) {
  return {
    teams: [
      { number: 1, members: lineup.team1 },
      { number: 2, members: lineup.team2 },
    ],
  }
}
