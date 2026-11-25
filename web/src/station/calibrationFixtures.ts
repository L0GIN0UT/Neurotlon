// Снимки калибровки для тестов экрана и модели.
import type { CalibratingState } from './calibration.ts'
import type { CalibrationStepView } from './types.ts'

export const step = (over: Partial<CalibrationStepView> = {}): CalibrationStepView => ({
  id: 'emg-cycle',
  step: 'cycle',
  signals: ['emg'],
  status: 'pending',
  progress: 0,
  segment: 0,
  segments_total: 4,
  phase: null,
  phase_left_s: null,
  reason_text: null,
  ...over,
})

export const baselineStep = (over: Partial<CalibrationStepView> = {}): CalibrationStepView =>
  step({ id: 'eeg-baseline', step: 'baseline', signals: ['eeg'], segments_total: 1, ...over })

export const calibrating = (over: Partial<CalibratingState> = {}): CalibratingState => ({
  kind: 'calibrating',
  players: [],
  link: 'live',
  sensors: [
    { signal: 'eeg', state: 'connected', battery: 84 },
    { signal: 'emg', state: 'connected', battery: 61 },
  ],
  eeg_method: 'alpha',
  steps: [step(), baselineStep()],
  current: 'emg-cycle',
  ready: false,
  ...over,
})
