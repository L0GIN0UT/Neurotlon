import { describe, expect, test } from 'vitest'
import cases from '../../../shared/participant-code.cases.json'
import { normalizeCode } from './participantCode.ts'

describe('normalizeCode vs shared cases', () => {
  test.each(Object.entries(cases.valid))('%j -> %s', (raw, expected) => {
    expect(normalizeCode(raw)).toBe(expected)
  })

  test.each(cases.invalid)('%j is rejected', (raw) => {
    expect(normalizeCode(raw)).toBeNull()
  })
})
