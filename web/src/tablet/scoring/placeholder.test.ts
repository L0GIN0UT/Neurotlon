import { expect, test } from 'vitest'
import { dartsPoints, footballPoints, pongPoints } from './placeholder.ts'

test('darts points are the sum of throws', () => {
  expect(dartsPoints([])).toBe(0)
  expect(dartsPoints([20, 15, 0, 3])).toBe(38)
})

test('football points are elements done plus accuracy', () => {
  expect(footballPoints([true, false, true, true], 7)).toBe(10)
  expect(footballPoints([false, false, false, false], 0)).toBe(0)
})

test('pong points are taken as entered', () => {
  expect(pongPoints(11)).toBe(11)
})
