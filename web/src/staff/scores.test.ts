import { describe, expect, test } from 'vitest'
import type { StoredResult } from './api.ts'
import { indexResults, scoreCell } from './scores.ts'

function result(extra: Partial<StoredResult>): StoredResult {
  return {
    id: 1,
    session_id: 's1',
    participant_code: 'NT01',
    discipline: 'darts',
    section: 'bci',
    outcome: 'completed',
    points: 7,
    wins: null,
    reason: null,
    comment: null,
    status: 'confirmed',
    source: 'station',
    finished_at: '2027-04-12T10:00:00Z',
    version: 1,
    voided: false,
    ...extra,
  }
}

describe('баллы участника', () => {
  test('дартс и футбол: баллы из лимита секции', () => {
    const index = indexResults([result({}), result({ discipline: 'football', points: 4, id: 2 })])
    expect(scoreCell(index, 'NT01', 'darts', 'bci', 10).text).toBe('7 из 10')
    expect(scoreCell(index, 'NT01', 'football', 'bci', 8).text).toBe('4 из 8')
  })

  test('без известного лимита показывает только баллы', () => {
    const index = indexResults([result({})])
    expect(scoreCell(index, 'NT01', 'darts', 'bci', undefined).text).toBe('7')
  })

  test('понг: счёт матча и победа или поражение, без «из»', () => {
    const index = indexResults([
      result({ discipline: 'pong', points: 21, wins: 1 }),
      result({ discipline: 'pong', participant_code: 'NT02', points: 15, wins: 0, id: 2 }),
    ])
    expect(scoreCell(index, 'NT01', 'pong', 'bci', 10)).toMatchObject({ text: '21 · победа', tone: 'good' })
    expect(scoreCell(index, 'NT02', 'pong', 'bci', 10).text).toBe('15 · поражение')
  })

  test('форма BCI и физическая считаются отдельно', () => {
    const index = indexResults([result({}), result({ section: 'physical', points: 9, id: 2 })])
    expect(scoreCell(index, 'NT01', 'darts', 'bci', 10).text).toBe('7 из 10')
    expect(scoreCell(index, 'NT01', 'darts', 'physical', 10).text).toBe('9 из 10')
  })

  test('«не пройдено» и отсутствие результата', () => {
    const index = indexResults([result({ outcome: 'not_completed', points: null })])
    expect(scoreCell(index, 'NT01', 'darts', 'bci', 10)).toMatchObject({ text: 'не пройдено', tone: 'warn' })
    expect(scoreCell(index, 'NT01', 'football', 'bci', 10)).toMatchObject({ text: '—', tone: 'none' })
  })

  test('аннулированные результаты не считаются, из двух берётся последний', () => {
    const index = indexResults([
      result({ points: 3, voided: true, id: 1 }),
      result({ points: 5, finished_at: '2027-04-12T10:05:00Z', id: 2 }),
      result({ points: 8, finished_at: '2027-04-12T10:10:00Z', id: 3 }),
    ])
    expect(scoreCell(index, 'NT01', 'darts', 'bci', 10).text).toBe('8 из 10')
  })
})
