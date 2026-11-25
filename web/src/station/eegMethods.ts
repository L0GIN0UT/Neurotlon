import type { SelectOption } from './Select.tsx'
import * as t from './texts.ts'

/** Значения метода ЭЭГ; список сверяется со схемой моста в eegMethods.test.ts. */
export const EEG_METHODS: SelectOption[] = [
  { value: 'alpha', label: t.SETUP.eegMethodAlpha },
  { value: 'emotions', label: t.SETUP.eegMethodEmotions },
]
