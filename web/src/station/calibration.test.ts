import { describe, expect, it } from 'vitest'
import {
  activeStep,
  burstsFor,
  EXTRAPOLATE_MS,
  inWindow,
  failedSignals,
  parseBatch,
  partOf,
  phaseWord,
  reasonText,
  RingBuffer,
  secondsLeft,
  segmentFills,
  sensorText,
  SignalStore,
  splitValid,
  statusText,
  stepTitle,
  timeToX,
  trackSignals,
  valueToY,
  WINDOW_MS,
} from './calibration.ts'
import type { Sample } from './calibration.ts'
import { baselineStep, calibrating, step } from './calibrationFixtures.ts'
import { commandForKey } from './flow.ts'

const parseFrames = (data: string) => parseBatch(data).frames
const sample = (t: number, ok = true, r: string | null = null, v = 0.5): Sample => ({ t, v, ok, r })

describe('steps', () => {
  it('shows the step named by current, else the running one, else the first unfinished', () => {
    const steps = [step({ status: 'done' }), baselineStep({ status: 'running' })]
    expect(activeStep(calibrating({ steps, current: 'emg-cycle' }))?.id).toBe('emg-cycle')
    expect(activeStep(calibrating({ steps, current: 1 }))?.id).toBe('eeg-baseline')
    expect(activeStep(calibrating({ steps, current: null }))?.id).toBe('eeg-baseline')
    const pending = [step({ status: 'done' }), baselineStep()]
    expect(activeStep(calibrating({ steps: pending, current: null }))?.id).toBe('eeg-baseline')
    expect(activeStep(calibrating({ steps: [] }))).toBeNull()
  })

  it('names the cards by sensor and says both arms for pong', () => {
    expect(stepTitle(step())).toBe('Мышца (ЭМГ)')
    expect(stepTitle(baselineStep())).toBe('Мозг (ЭЭГ)')
    expect(stepTitle(step({ signals: ['emg_left', 'emg_right'] }))).toBe('Мышцы игроков')
  })

  it('shows the failure reason, or a default one, on a failed card', () => {
    expect(statusText(step({ status: 'failed', reason_text: 'датчик отключён' }))).toBe('датчик отключён')
    expect(statusText(step({ status: 'failed' }))).toBe('Шаг не пройден')
    expect(statusText(step({ status: 'pending' }))).toBe('Ожидает')
    expect(statusText(step({ status: 'running' }))).toBe('Идёт')
    expect(statusText(step({ status: 'done' }))).toBe('Готово')
  })

  it('tells what to do in each phase', () => {
    expect(phaseWord(step({ phase: 'tense' }))).toBe('НАПРЯГИТЕ')
    expect(phaseWord(step({ phase: 'relax' }))).toBe('РАССЛАБЬТЕ')
    expect(phaseWord(step({ phase: null }))).toBe('Приготовьтесь')
  })

  it('counts whole seconds up and falls back to progress for the dot', () => {
    expect(secondsLeft(step({ status: 'running', phase_left_s: 3.2 }))).toBe(4)
    expect(secondsLeft(step({ status: 'running', phase_left_s: 0 }))).toBe(0)
    expect(secondsLeft(step({ status: 'pending', phase_left_s: 3 }))).toBeNull()
    expect(secondsLeft(step({ status: 'running' }))).toBeNull()
    expect(secondsLeft(baselineStep({ status: 'running', progress: 0 }))).toBe(12)
    expect(secondsLeft(baselineStep({ status: 'running', progress: 0.5 }))).toBe(6)
  })

  it('fills four segments from the overall progress, tense and relax alternating', () => {
    const fills = segmentFills(step({ status: 'running', progress: 0.375 }))
    expect(fills.map((f) => f.fill)).toEqual([1, 0.5, 0, 0])
    expect(fills.map((f) => f.tone)).toEqual(['tense', 'relax', 'tense', 'relax'])
    expect(fills.map((f) => f.current)).toEqual([false, true, false, false])
    expect(segmentFills(step({ status: 'done', progress: 0 })).every((f) => f.fill === 1)).toBe(true)
    expect(segmentFills(step({ status: 'running', progress: Number.NaN })).every((f) => f.fill === 0)).toBe(true)
  })

  it('orders the chart tracks: brain, muscle, then left and right', () => {
    expect(trackSignals([step(), baselineStep()])).toEqual(['eeg', 'emg'])
    expect(trackSignals([step({ signals: ['emg_right', 'emg_left'] })])).toEqual(['emg_left', 'emg_right'])
  })

  it('writes the sensor chip with its state and battery', () => {
    expect(sensorText({ signal: 'emg', state: 'connected', battery: 61.4 })).toBe('Датчик мышцы: подключён, 61 %')
    expect(sensorText({ signal: 'eeg', state: 'disconnected', battery: null })).toBe('Датчик мозга: отключён')
  })
})

describe('keys on the calibration screen', () => {
  it('continues on Enter only when everything is ready', () => {
    expect(commandForKey(calibrating(), 'Enter')).toBeNull()
    expect(commandForKey(calibrating({ ready: true }), 'Enter')).toEqual({ action: 'calibration_continue' })
  })

  it('goes back on Escape at any time and ignores other keys', () => {
    expect(commandForKey(calibrating(), 'Escape')).toEqual({ action: 'back' })
    expect(commandForKey(calibrating({ ready: true }), 'Escape')).toEqual({ action: 'back' })
    expect(commandForKey(calibrating({ ready: true }), '7')).toBeNull()
  })
})

describe('reasons', () => {
  it('translates the bridge reasons into fixed Russian texts', () => {
    expect(reasonText('artifact')).toBe('артефакт')
    expect(reasonText('no_contact')).toBe('нет контакта')
    expect(reasonText('disconnected')).toBe('нет контакта')
    expect(reasonText('stale')).toBe('нет данных')
    expect(reasonText('not_calibrated')).toBe('не откалиброван')
  })

  it('keeps an already translated reason and falls back to "no data"', () => {
    expect(reasonText('артефакт')).toBe('артефакт')
    expect(reasonText('что-то новое')).toBe('нет данных')
    expect(reasonText(null)).toBe('нет данных')
    expect(reasonText('')).toBe('нет данных')
  })
})

describe('RingBuffer', () => {
  it('keeps the newest items in order and drops the oldest', () => {
    const ring = new RingBuffer<number>(3)
    ring.push(1)
    ring.push(2)
    expect(ring.toArray()).toEqual([1, 2])
    ring.push(3)
    ring.push(4)
    ring.push(5)
    expect(ring.toArray()).toEqual([3, 4, 5])
    expect(ring.size).toBe(3)
  })

  it('can be emptied and reused', () => {
    const ring = new RingBuffer<string>(2)
    ring.push('a')
    ring.clear()
    expect(ring.toArray()).toEqual([])
    ring.push('b')
    expect(ring.toArray()).toEqual(['b'])
  })
})

describe('parseFrames', () => {
  it('reads a frame with values, validity, reasons and bursts', () => {
    const [frame] = parseFrames(
      JSON.stringify({
        t_ms: 1000,
        signals: { emg: { v: 0.4, ok: true, r: null }, eeg: { v: 2, ok: false, r: 'artifact' } },
        bursts: [{ signal: 'emg', t_ms: 990, rise: 0.3 }],
      }),
    )
    expect(frame?.t).toBe(1000)
    expect(frame?.signals.emg).toEqual({ v: 0.4, ok: true, r: null })
    expect(frame?.signals.eeg).toEqual({ v: 1, ok: false, r: 'artifact' })
    expect(frame?.bursts).toEqual([{ signal: 'emg', t: 990, rise: 0.3 }])
  })

  it('reads several samples in one frame', () => {
    const frames = parseFrames(
      JSON.stringify({
        samples: [
          { t_ms: 100, signals: { emg: { v: 0.1, ok: true, r: null } } },
          { t_ms: 120, signals: { emg: { v: 0.2, ok: true, r: null } } },
        ],
        bursts: [{ signal: 'emg', t_ms: 110, rise: 0.2 }],
      }),
    )
    expect(frames.map((f) => f.t)).toEqual([100, 120])
    expect(frames[1]?.bursts).toHaveLength(1)
  })

  it('drops garbage without throwing', () => {
    expect(parseFrames('not json')).toEqual([])
    expect(parseFrames('null')).toEqual([])
    expect(parseFrames('[]')).toEqual([])
    expect(parseFrames('{"signals":{}}')).toEqual([])
    const [frame] = parseFrames('{"t_ms":1,"signals":{"emg":{"v":"x"},"eeg":{"v":0.5}},"bursts":[{"signal":1}]}')
    expect(Object.keys(frame?.signals ?? {})).toEqual(['eeg'])
    expect(frame?.signals.eeg?.ok).toBe(true)
    expect(frame?.bursts).toEqual([])
  })
})

describe('gen of the bridge', () => {
  const batch = (gen: number | null, t: number) =>
    parseBatch(JSON.stringify({ gen, samples: [{ t_ms: t, signals: { emg: { v: 0.5, ok: true } } }], bursts: [] }))

  it('reads gen from the frame', () => {
    expect(batch(3, 100).gen).toBe(3)
    expect(parseBatch('{"samples":[]}').gen).toBeNull()
    expect(parseBatch('oops')).toEqual({ gen: null, frames: [] })
  })

  it('keeps the buffer while gen is the same and drops it when the bridge restarts', () => {
    const store = new SignalStore()
    store.apply(batch(1, 5000), 0)
    store.apply(batch(1, 5100), 10)
    expect(store.samples('emg')).toHaveLength(2)
    store.apply(batch(2, 40), 20)
    expect(store.samples('emg').map((s) => s.t)).toEqual([40])
    expect(store.gen).toBe(2)
    expect(store.lastT).toBe(40)
  })

  it('clears on a new gen even when the new clock is ahead', () => {
    const store = new SignalStore()
    store.apply(batch(1, 100), 0)
    store.apply(batch(2, 9_000_000), 5)
    expect(store.samples('emg').map((s) => s.t)).toEqual([9_000_000])
  })
})

describe('parts', () => {
  const pong = step({
    signals: ['emg_left', 'emg_right'],
    status: 'failed',
    reason_text: 'нет контакта',
    parts: [
      { signal: 'emg_left', status: 'done', progress: 1, reason_text: null },
      { signal: 'emg_right', status: 'failed', progress: 0.4, reason_text: 'нет контакта' },
    ],
  })

  it('finds the part of a signal and falls back to the step', () => {
    expect(partOf(pong, 'emg_right').status).toBe('failed')
    expect(partOf(step({ status: 'running', progress: 0.3 }), 'emg')).toMatchObject({ status: 'running', progress: 0.3 })
  })

  it('lists only the signals that failed', () => {
    expect(failedSignals(pong)).toEqual(['emg_right'])
    expect(failedSignals(step({ status: 'failed' }))).toEqual(['emg'])
    expect(failedSignals(step({ status: 'done' }))).toEqual([])
  })
})

describe('SignalStore', () => {
  const frame = (t: number, v = 0.5) => ({ t, signals: { emg: { v, ok: true, r: null } }, bursts: [] })

  it('stores samples per signal and the bursts separately', () => {
    const store = new SignalStore()
    store.push({ ...frame(100), bursts: [{ signal: 'emg', t: 100, rise: 0.4 }] }, 5)
    store.push(frame(200), 105)
    expect(store.samples('emg').map((s) => s.t)).toEqual([100, 200])
    expect(store.samples('eeg')).toEqual([])
    expect(store.bursts()).toHaveLength(1)
  })

  it('has no window end before data and moves it smoothly up to a limit between frames', () => {
    const store = new SignalStore()
    expect(store.windowEnd(0)).toBeNull()
    store.push(frame(1000), 50)
    expect(store.windowEnd(50)).toBe(1000)
    expect(store.windowEnd(100)).toBe(1050)
    expect(store.windowEnd(50 + 10_000)).toBe(1000 + EXTRAPOLATE_MS)
    expect(store.windowEnd(0)).toBe(1000)
  })

  it('starts over when the bridge clock jumps back', () => {
    const store = new SignalStore()
    store.push(frame(50_000), 0)
    store.push(frame(100), 10)
    expect(store.samples('emg').map((s) => s.t)).toEqual([100])
    expect(store.lastT).toBe(100)
  })

  it('never grows beyond its capacity', () => {
    const store = new SignalStore()
    for (let i = 0; i < 5000; i += 1) store.push(frame(i * 10), i)
    expect(store.samples('emg').length).toBeLessThanOrEqual(1500)
    expect(store.samples('emg').at(-1)?.t).toBe(49_990)
  })
})

describe('splitValid', () => {
  it('returns nothing for no samples', () => {
    expect(splitValid([])).toEqual([])
  })

  it('splits a run into valid and grey stretches', () => {
    const samples = [
      sample(0),
      sample(100),
      sample(200, false, 'artifact'),
      sample(300, false, 'artifact'),
      sample(400),
    ]
    expect(splitValid(samples)).toEqual([
      { ok: true, reason: null, start: 0, end: 1 },
      { ok: false, reason: 'артефакт', start: 2, end: 3 },
      { ok: true, reason: null, start: 4, end: 4 },
    ])
  })

  it('splits grey stretches when the reason changes', () => {
    const parts = splitValid([sample(0, false, 'no_contact'), sample(1, false, 'stale'), sample(2, false, 'weird')])
    expect(parts.map((p) => p.reason)).toEqual(['нет контакта', 'нет данных'])
    expect(parts[1]).toMatchObject({ start: 1, end: 2 })
  })

  it('treats all-grey and single-sample input', () => {
    expect(splitValid([sample(0, false, 'not_calibrated')])).toEqual([
      { ok: false, reason: 'не откалиброван', start: 0, end: 0 },
    ])
  })
})

describe('window geometry', () => {
  const samples = [sample(0), sample(4000), sample(9000), sample(12_000), sample(15_000)]

  it('keeps samples of the last 10 s plus one before the edge', () => {
    expect(inWindow(samples, 15_000).map((s) => s.t)).toEqual([4000, 9000, 12_000, 15_000])
    expect(inWindow(samples, 15_000, 2000).map((s) => s.t)).toEqual([12_000, 15_000])
    expect(inWindow(samples, 100_000)).toEqual([])
    expect(inWindow([], 1)).toEqual([])
  })

  it('maps the window edges to the plot edges', () => {
    expect(timeToX(5000, 15_000, 100, 800)).toBe(100)
    expect(timeToX(15_000, 15_000, 100, 800)).toBe(900)
    expect(timeToX(10_000, 15_000, 100, 800)).toBe(500)
    expect(WINDOW_MS).toBe(10_000)
  })

  it('maps 0 to the bottom and 1 to the top of a lane, clamping outliers', () => {
    expect(valueToY(0, 10, 200)).toBe(210)
    expect(valueToY(1, 10, 200)).toBe(10)
    expect(valueToY(0.25, 0, 100)).toBe(75)
    expect(valueToY(3, 10, 200)).toBe(10)
    expect(valueToY(-1, 10, 200)).toBe(210)
  })

  it('picks bursts of one signal inside the window', () => {
    const bursts = [
      { signal: 'emg', t: 1000, rise: 0.2 },
      { signal: 'emg', t: 9000, rise: 0.3 },
      { signal: 'eeg', t: 9000, rise: 0.3 },
      { signal: 'emg', t: 16_000, rise: 0.3 },
    ]
    expect(burstsFor(bursts, 'emg', 12_000).map((b) => b.t)).toEqual([9000])
    expect(burstsFor(bursts, 'emg', 20_000).map((b) => b.t)).toEqual([16_000])
  })
})
