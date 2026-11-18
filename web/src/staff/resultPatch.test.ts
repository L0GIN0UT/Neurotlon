import { describe, expect, test } from 'vitest'
import type { StoredResult } from './api.ts'
import { buildPatch, describeResult, draftOf } from './resultPatch.ts'

function row(extra: Partial<StoredResult> = {}): StoredResult {
  return {
    id: 1,
    session_id: 's',
    participant_code: 'NT01',
    discipline: 'darts',
    section: 'bci',
    outcome: 'completed',
    points: 40,
    wins: null,
    reason: null,
    comment: null,
    status: 'confirmed',
    source: 'station',
    finished_at: '2027-01-01T09:00:00Z',
    version: 1,
    voided: false,
    ...extra,
  }
}

describe('buildPatch', () => {
  test('причина обязательна и не длиннее 200 символов', () => {
    const base = row()
    expect(buildPatch(base, { ...draftOf(base), points: '41' })).toEqual({
      error: 'Укажите причину исправления',
    })
    expect(buildPatch(base, { ...draftOf(base), points: '41', changeReason: '   ' })).toEqual({
      error: 'Укажите причину исправления',
    })
    expect(
      'error' in buildPatch(base, { ...draftOf(base), points: '41', changeReason: 'x'.repeat(201) }),
    ).toBe(true)
  })

  test('в тело попадают только изменённые поля', () => {
    const base = row()
    expect(buildPatch(base, { ...draftOf(base), points: '45', changeReason: ' пересчёт ' })).toEqual({
      patch: { points: 45, change_reason: 'пересчёт' },
    })
  })

  test('без изменений — ошибка', () => {
    const base = row()
    expect(buildPatch(base, { ...draftOf(base), changeReason: 'зачем' })).toEqual({
      error: 'Нет изменений',
    })
  })

  test('очки: число от 0 до 1000', () => {
    const base = row()
    for (const points of ['', 'abc', '-1', '1001']) {
      expect(buildPatch(base, { ...draftOf(base), points, changeReason: 'r' })).toEqual({
        error: 'Очки — число от 0 до 1000',
      })
    }
  })

  test('переход в «не пройдено» отправляет исход и причину', () => {
    const base = row()
    const draft = { ...draftOf(base), outcome: 'not_completed' as const, changeReason: 'r' }
    expect(buildPatch(base, draft)).toEqual({ error: 'Выберите причину «не пройдено»' })
    expect(buildPatch(base, { ...draft, reason: 'health' })).toEqual({
      patch: { outcome: 'not_completed', reason: 'health', change_reason: 'r' },
    })
  })

  test('возврат в «пройдено» отправляет исход и очки', () => {
    const base = row({ outcome: 'not_completed', points: null, reason: 'health' })
    const draft = { ...draftOf(base), outcome: 'completed' as const, points: '0', changeReason: 'r' }
    expect(buildPatch(base, draft)).toEqual({
      patch: { outcome: 'completed', points: 0, change_reason: 'r' },
    })
  })

  test('победы только для понга', () => {
    const pong = row({ discipline: 'pong', wins: 0, points: 7 })
    expect(buildPatch(pong, { ...draftOf(pong), wins: '1', changeReason: 'r' })).toEqual({
      patch: { wins: 1, change_reason: 'r' },
    })
    const darts = row()
    expect(buildPatch(darts, { ...draftOf(darts), wins: '1', changeReason: 'r' })).toEqual({
      error: 'Нет изменений',
    })
  })

  test('комментарий можно очистить', () => {
    const base = row({ comment: 'старый' })
    expect(buildPatch(base, { ...draftOf(base), comment: ' ', changeReason: 'r' })).toEqual({
      patch: { comment: null, change_reason: 'r' },
    })
  })
})

describe('describeResult', () => {
  test('очки и победы', () => {
    expect(describeResult(row({ discipline: 'pong', wins: 1, points: 11 }))).toBe(
      'NT01 · Понг · BCI: очки 11, побед 1',
    )
  })

  test('не пройдено с причиной', () => {
    expect(describeResult(row({ outcome: 'not_completed', points: null, reason: 'equipment' }))).toBe(
      'NT01 · Дартс · BCI: не пройдено (Неисправность оборудования)',
    )
  })
})
