import { expect, test } from 'vitest'
import { POINTS_MAX, pongPoints, sectionLimit, sectionPoints } from './placeholder.ts'

test('section and pong points are taken as entered', () => {
  expect(sectionPoints(7.5)).toBe(7.5)
  expect(pongPoints(11)).toBe(11)
})

test('limit is the discipline limit, or the schema ceiling when unknown', () => {
  expect(sectionLimit(10)).toBe(10)
  expect(sectionLimit(null)).toBe(POINTS_MAX)
  expect(sectionLimit(undefined)).toBe(POINTS_MAX)
})
