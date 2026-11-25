import { describe, expect, it } from 'vitest'
import schema from '../../../shared/bridge-protocol.schema.json'
import { EEG_METHODS } from './eegMethods.ts'

describe('EEG method list', () => {
  it('offers exactly the methods of the bridge protocol schema', () => {
    const offered = EEG_METHODS.map((option) => option.value).sort()
    expect(offered).toEqual([...schema.$defs.EegMethod.enum].sort())
  })
})
