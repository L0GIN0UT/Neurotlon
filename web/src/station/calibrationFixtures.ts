// Снимки калибровки для тестов экрана и модели.
import type { CalibratingState } from './calibration.ts'
import type { CalibrationStepView } from './types.ts'

export const step = (over: Partial<CalibrationStepView> = {}): CalibrationStepView => ({
  id: 'emg',
  step: 'cycle',
  signals: ['emg'],
  status: 'pending',
  progress: 0,
  segment: 0,
  segments_total: 4,
  phase: null,
  phase_left_s: null,
  reason_text: null,
  stage: 'waiting',
  countdown_s: null,
  title: 'Калибровка ЭМГ',
  ...over,
})

export const baselineStep = (over: Partial<CalibrationStepView> = {}): CalibrationStepView =>
  step({ id: 'eeg', title: 'Калибровка ЭЭГ', step: 'baseline', signals: ['eeg'], segments_total: 1, ...over })

export const calibrating = (over: Partial<CalibratingState> = {}): CalibratingState => ({
  kind: 'calibrating',
  players: [],
  link: 'live',
  sensors: [
    { signal: 'eeg', title: 'ЭЭГ', status: 'connected', state: 'ok', battery: 84 },
    { signal: 'emg', title: 'ЭМГ', status: 'connected', state: 'ok', battery: 61 },
  ],
  eeg_method: 'alpha',
  steps: [step(), baselineStep()],
  current: 'emg',
  ready: false,
  stage: over.stage ?? (over.ready ? 'review' : over.steps?.length === 0 ? 'connecting' : 'running'),
  connect_error: null,
  ...over,
})
