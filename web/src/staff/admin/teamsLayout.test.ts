import { describe, expect, test } from 'vitest'
import { dropPreview, dropSlots, edgeScroll, moveTo, slotAt, zoneAt } from './teamsLayout.ts'
import type { Lineup, Locks } from './teamsLayout.ts'

const lineup: Lineup = { pool: ['NT09'], team1: ['NT01', 'NT02', 'NT03'], team2: ['NT04'] }
const none: Locks = new Map()

describe('место вставки по координатам', () => {
  test('считает карточки, середина которых выше указателя', () => {
    const mids = [25, 85, 145]
    expect(slotAt(10, mids)).toBe(0)
    expect(slotAt(26, mids)).toBe(1)
    expect(slotAt(100, mids)).toBe(2)
    expect(slotAt(999, mids)).toBe(3)
    expect(slotAt(10, [])).toBe(0)
  })

  test('область под указателем; между колонками и вне их null', () => {
    const zones = {
      team1: { left: 0, right: 100, top: 0, bottom: 500 },
      team2: { left: 200, right: 300, top: 0, bottom: 500 },
      pool: { left: -200, right: -10, top: 0, bottom: 300 },
    }
    expect(zoneAt(50, 10, zones)).toBe('team1')
    expect(zoneAt(250, 400, zones)).toBe('team2')
    expect(zoneAt(-50, 200, zones)).toBe('pool')
    expect(zoneAt(150, 10, zones)).toBeNull()
    expect(zoneAt(50, 600, zones)).toBeNull()
  })

  test('автопрокрутка: у верха вверх, у низа вниз, в середине нет', () => {
    expect(edgeScroll(400, 800)).toBe(0)
    expect(edgeScroll(10, 800)).toBeLessThan(0)
    expect(edgeScroll(790, 800)).toBeGreaterThan(0)
    expect(edgeScroll(0, 800)).toBe(-22)
    expect(edgeScroll(10, 800)).toBeGreaterThan(edgeScroll(0, 800))
  })
})

describe('допустимые места вставки', () => {
  test('без закреплённых допустимы все места, в том числе в пустую команду', () => {
    expect(dropSlots(lineup, none, 'NT01', 'team1')).toEqual([true, true, true])
    expect(dropSlots(lineup, none, 'NT09', 'team2')).toEqual([true, true])
    expect(dropSlots({ pool: [], team1: ['NT01'], team2: [] }, none, 'NT01', 'team2')).toEqual([true])
  })

  test('вставка вокруг закреплённого: закреплённый остаётся на месте', () => {
    const locks: Locks = new Map([['NT02', { area: 'team1', index: 1 }]])
    expect(dropPreview(lineup, locks, 'NT01', 'team1', 2)?.team1).toEqual(['NT03', 'NT02', 'NT01'])
    // место до закреплённого даёт тот же порядок: ход ничего не меняет
    expect(moveTo(lineup, locks, 'NT01', 'team1', 0)).toBeNull()
  })

  test('нельзя оставить дыру перед закреплённым и взять закреплённого', () => {
    const locks: Locks = new Map([['NT02', { area: 'team1', index: 1 }]])
    const two: Lineup = { pool: [], team1: ['NT01', 'NT02'], team2: [] }
    expect(dropSlots(two, locks, 'NT01', 'team2')).toEqual([false])
    expect(dropSlots(two, locks, 'NT01', 'pool')).toEqual([false])
    expect(dropPreview(two, locks, 'NT02', 'team2')).toBeNull()
    expect(dropSlots(two, locks, 'NT01', 'team1')).toEqual([true, true])
  })
})
