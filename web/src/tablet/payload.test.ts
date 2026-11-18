import { describe, expect, test } from 'vitest'
import { PayloadError, buildSubmission } from './payload.ts'
import type { SubmissionInput } from './payload.ts'

const SESSION = '0f8c7a52-3c1e-4c5e-9a57-2d6a3b1f9e10'
const base = {
  sessionId: SESSION,
  section: 'physical',
  finishedAt: new Date('2027-04-12T07:05:00Z'),
  winner: null,
} as const

function input(overrides: Partial<SubmissionInput>): SubmissionInput {
  return { ...base, discipline: 'darts', entries: [], ...overrides }
}

describe('buildSubmission', () => {
  test('darts: points, no wins', () => {
    const payload = buildSubmission(
      input({ entries: [{ code: 'NT07', completed: true, points: 42.5 }] }),
    )
    expect(payload).toEqual({
      session_id: SESSION,
      discipline: 'darts',
      section: 'physical',
      finished_at: '2027-04-12T07:05:00.000Z',
      entries: [{ participant_code: 'NT07', outcome: 'completed', points: 42.5 }],
    })
  })

  test('football: completed entry has no wins', () => {
    const payload = buildSubmission(
      input({
        discipline: 'football',
        entries: [{ code: 'NT11', completed: true, points: 9 }],
      }),
    )
    expect(payload.entries[0]).toEqual({
      participant_code: 'NT11',
      outcome: 'completed',
      points: 9,
    })
  })

  test('not completed: reason and trimmed comment, no points or wins', () => {
    const payload = buildSubmission(
      input({
        entries: [{ code: 'NT11', completed: false, reason: 'equipment', comment: '  сломан ' }],
      }),
    )
    expect(payload.entries[0]).toEqual({
      participant_code: 'NT11',
      outcome: 'not_completed',
      reason: 'equipment',
      comment: 'сломан',
    })
  })

  test('not completed without comment omits the field', () => {
    const payload = buildSubmission(
      input({ entries: [{ code: 'NT11', completed: false, reason: 'health', comment: ' ' }] }),
    )
    expect(payload.entries[0]).not.toHaveProperty('comment')
  })

  test('pong: exactly one winner with wins 1 and 0', () => {
    const payload = buildSubmission(
      input({
        discipline: 'pong',
        winner: 'NT14',
        entries: [
          { code: 'NT03', completed: true, points: 7 },
          { code: 'NT14', completed: true, points: 11 },
        ],
      }),
    )
    expect(payload.entries.map((e) => e.wins)).toEqual([0, 1])
  })

  test('pong: one player did not finish, finisher gets wins 1, the other has no wins', () => {
    const payload = buildSubmission(
      input({
        discipline: 'pong',
        entries: [
          { code: 'NT03', completed: true, points: 7 },
          { code: 'NT14', completed: false, reason: 'no_show' },
        ],
      }),
    )
    expect(payload.entries[0]?.wins).toBe(1)
    expect(payload.entries[1]).not.toHaveProperty('wins')
    expect(payload.entries[1]).not.toHaveProperty('points')
  })

  test('pong: both not completed has no wins at all', () => {
    const payload = buildSubmission(
      input({
        discipline: 'pong',
        entries: [
          { code: 'NT03', completed: false, reason: 'other' },
          { code: 'NT14', completed: false, reason: 'other' },
        ],
      }),
    )
    expect(payload.entries.every((e) => !('wins' in e))).toBe(true)
  })
})

describe('buildSubmission rejects invalid input', () => {
  const player = (code: string, points = 1) => ({ code, completed: true, points }) as const

  test.each([
    [
      'pong without winner',
      input({ discipline: 'pong', entries: [player('NT03'), player('NT14')] }),
    ],
    [
      'pong with a stranger as winner',
      input({
        discipline: 'pong',
        winner: 'NT05',
        entries: [player('NT03'), player('NT14')],
      }),
    ],
    ['pong with one player', input({ discipline: 'pong', entries: [player('NT03')] })],
    [
      'pong with the same player twice',
      input({ discipline: 'pong', winner: 'NT03', entries: [player('NT03'), player('NT03')] }),
    ],
    ['darts with two players', input({ entries: [player('NT03'), player('NT14')] })],
    ['darts with a winner', input({ winner: 'NT03', entries: [player('NT03')] })],
    ['no entries', input({ entries: [] })],
    ['negative points', input({ entries: [player('NT03', -1)] })],
    ['points above 1000', input({ entries: [player('NT03', 1001)] })],
    ['points above the section limit', input({ maxPoints: 10, entries: [player('NT03', 10.5)] })],
    ['NaN points', input({ entries: [player('NT03', Number.NaN)] })],
    [
      'comment over 200',
      input({
        entries: [{ code: 'NT03', completed: false, reason: 'other', comment: 'я'.repeat(201) }],
      }),
    ],
  ])('%s', (_name, value) => {
    expect(() => buildSubmission(value)).toThrow(PayloadError)
  })
})

describe('section points limit', () => {
  const entry = (points: number) => ({ code: 'NT03', completed: true, points }) as const

  test('exactly the limit is accepted for darts and football', () => {
    for (const discipline of ['darts', 'football'] as const) {
      const payload = buildSubmission(input({ discipline, maxPoints: 10, entries: [entry(10)] }))
      expect(payload.entries[0]?.points).toBe(10)
    }
  })

  test('the message names the limit', () => {
    expect(() => buildSubmission(input({ maxPoints: 10, entries: [entry(11)] }))).toThrow(
      'Очки должны быть от 0 до 10',
    )
  })

  test('pong points are not limited by it', () => {
    const payload = buildSubmission(
      input({
        discipline: 'pong',
        maxPoints: 10,
        winner: 'NT03',
        entries: [entry(50), { code: 'NT14', completed: true, points: 7 }],
      }),
    )
    expect(payload.entries.map((e) => e.points)).toEqual([50, 7])
  })
})
