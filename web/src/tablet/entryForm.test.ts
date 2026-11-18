import { describe, expect, test } from 'vitest'
import { emptyForm, formPoints, sectionPointsProblem, stepPoints } from './entryForm.ts'
import { PayloadError } from './payload.ts'

const form = (points: string) => ({ ...emptyForm(), points })

describe('sectionPointsProblem', () => {
  test.each(['0', '0.5', '5', '10', '9,5', ''])('%j is fine for limit 10', (text) => {
    expect(sectionPointsProblem(text, 10)).toBeNull()
  })

  test.each(['-1', '10.5', '11', 'abc', '0.3', '1e3'])('%j is refused for limit 10', (text) => {
    expect(sectionPointsProblem(text, 10)).toBe('Очки за секцию — число от 0 до 10 с шагом 0,5')
  })

  test('without a known limit the schema ceiling applies', () => {
    expect(sectionPointsProblem('1000', null)).toBeNull()
    expect(sectionPointsProblem('1001', null)).not.toBeNull()
  })
})

describe('stepPoints', () => {
  test('moves by half a point inside 0…limit', () => {
    expect(stepPoints('', 1, 10)).toBe('0.5')
    expect(stepPoints('2', 1, 10)).toBe('2.5')
    expect(stepPoints('2,5', -1, 10)).toBe('2')
  })

  test('clamps at both ends', () => {
    expect(stepPoints('0', -1, 10)).toBe('0')
    expect(stepPoints('10', 1, 10)).toBe('10')
    expect(stepPoints('9.5', 1, 10)).toBe('10')
  })
})

describe('formPoints', () => {
  test('darts and football read the limit', () => {
    expect(formPoints('darts', form('7.5'), 10)).toBe(7.5)
    expect(formPoints('football', form('10'), 10)).toBe(10)
    expect(() => formPoints('darts', form('11'), 10)).toThrow(PayloadError)
    expect(() => formPoints('football', form(''), 10)).toThrow('Введите очки за секцию')
  })

  test('pong is not limited by it', () => {
    expect(formPoints('pong', form('25'), 10)).toBe(25)
    expect(() => formPoints('pong', form('1001'), null)).toThrow(PayloadError)
  })
})
