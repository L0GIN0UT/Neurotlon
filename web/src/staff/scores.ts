// Баллы участника в списке админки: по результатам секций, ничего не хранится отдельно.
import { DISCIPLINES } from '../shared/types.ts'
import type { Discipline, Section } from '../shared/types.ts'
import type { StoredResult } from './api.ts'

export const SECTIONS: Section[] = ['bci', 'physical']

export interface Cell {
  /** Текст ячейки; `—` — результата нет. */
  text: string
  /** Пояснение к ячейке (всплывающая подсказка). */
  title?: string
  tone: 'none' | 'good' | 'warn'
}

type Key = `${string}|${Discipline}|${Section}`
const keyOf = (code: string, discipline: Discipline, section: Section): Key =>
  `${code}|${discipline}|${section}`

/** Результаты по участнику, дисциплине и секции: аннулированные не считаются, из нескольких берём последний. */
export function indexResults(items: StoredResult[]): Map<Key, StoredResult> {
  const map = new Map<Key, StoredResult>()
  for (const item of items) {
    if (item.voided) continue
    const key = keyOf(item.participant_code, item.discipline, item.section)
    const known = map.get(key)
    if (!known || known.finished_at < item.finished_at) map.set(key, item)
  }
  return map
}

/**
 * Дартс и футбол: «баллы из лимита секции». Понг: очки здесь счёт матча без предела, поэтому
 * «счёт и победа или поражение».
 */
export function scoreCell(
  results: Map<Key, StoredResult>,
  code: string,
  discipline: Discipline,
  section: Section,
  limit: number | undefined,
): Cell {
  const result = results.get(keyOf(code, discipline, section))
  if (!result) return { text: '—', tone: 'none' }
  if (result.outcome === 'not_completed') {
    return { text: 'не пройдено', tone: 'warn', title: result.comment ?? undefined }
  }
  const points = result.points ?? 0
  if (discipline === 'pong') {
    const verdict = result.wins === 1 ? 'победа' : result.wins === 0 ? 'поражение' : ''
    return {
      text: verdict ? `${points} · ${verdict}` : String(points),
      tone: result.wins === 1 ? 'good' : 'none',
      title: 'Счёт матча',
    }
  }
  return {
    text: limit === undefined ? String(points) : `${points} из ${limit}`,
    tone: 'none',
  }
}

export { DISCIPLINES }
