// Модель экрана «Калибровка»: чистые функции и буфер сигналов. Без React и без DOM.
import * as t from './texts.ts'
import type { CalibrationPartView, CalibrationStepView, SensorView, StateView } from './types.ts'

export type CalibratingState = Extract<StateView, { kind: 'calibrating' }>

/** Окно графика, мс. */
export const WINDOW_MS = 10_000
/** Сколько мс после последнего кадра линия «едет» сама, пока не пришёл следующий (кадр раз в 100 мс). */
export const EXTRAPOLATE_MS = 250
/** Длительность взгляда на точку, с: если лаунчер не прислал остаток. */
export const BASELINE_S = 12
/** Горизонтальные линии сетки шкалы 0…1. */
export const GRID = [0, 0.25, 0.5, 0.75, 1] as const

const TRACK_ORDER = ['eeg', 'emg', 'emg_left', 'emg_right']

// ---------- шаги ----------

/** Шаг, который сейчас на экране: по `current`, иначе идущий, иначе первый непройденный, иначе последний. */
export function activeStep(state: CalibratingState): CalibrationStepView | null {
  const { steps, current } = state
  if (steps.length === 0) return null
  const byCurrent =
    typeof current === 'number' ? steps[current] : steps.find((step) => step.id === current)
  if (byCurrent) return byCurrent
  return (
    steps.find((s) => s.status === 'running') ??
    steps.find((s) => s.status !== 'done') ??
    steps[steps.length - 1] ??
    null
  )
}

export const isPong = (steps: readonly CalibrationStepView[]): boolean =>
  steps.some((s) => s.signals.length > 1 || s.signals.includes('emg_left'))

/** Название карточки: «Мышца (ЭМГ)», «Мозг (ЭЭГ)», в понге — «Мышцы игроков». */
export function stepTitle(step: CalibrationStepView): string {
  if (step.signals.length > 1) return t.CALIB.stepBoth
  const [first] = step.signals
  return (first && t.CALIB.stepNames[first]) || first || step.id
}

export const stepSubtitle = (step: CalibrationStepView): string =>
  step.step === 'baseline' ? t.CALIB.stepBaseline : t.CALIB.stepCycle

export function statusText(step: CalibrationStepView): string {
  switch (step.status) {
    case 'pending':
      return t.CALIB.statusPending
    case 'running':
      return t.CALIB.statusRunning
    case 'done':
      return t.CALIB.statusDone
    case 'failed':
      return step.reason_text?.trim() || t.CALIB.failedDefault
  }
}

export const clamp01 = (x: number): number => (Number.isFinite(x) ? Math.min(1, Math.max(0, x)) : 0)

/** Подпись фазы цикла: что делать участнику прямо сейчас. */
export function phaseWord(step: CalibrationStepView): string {
  if (step.phase === 'tense') return t.CALIB.tense
  if (step.phase === 'relax') return t.CALIB.relax
  return t.CALIB.getReady
}

export function phaseHint(step: CalibrationStepView): string {
  if (step.phase === 'tense') return t.CALIB.tenseHint
  if (step.phase === 'relax') return t.CALIB.relaxHint
  return t.CALIB.readyHint
}

/** Целые секунды до конца фазы (с округлением вверх); для `baseline` без остатка — по прогрессу. */
export function secondsLeft(step: CalibrationStepView): number | null {
  if (step.status !== 'running') return null
  if (step.phase_left_s !== null && Number.isFinite(step.phase_left_s)) {
    return Math.max(0, Math.ceil(step.phase_left_s))
  }
  if (step.step === 'baseline') return Math.max(0, Math.ceil((1 - clamp01(step.progress)) * BASELINE_S))
  return null
}

export interface SegmentFill {
  /** Доля заполнения 0…1. */
  fill: number
  /** Цвет сегмента: напряг или расслабление (в цикле они чередуются). */
  tone: 'tense' | 'relax'
  current: boolean
}

/** Полоса сегментов шага: заполнение считается по общему прогрессу, а не по номеру сегмента. */
export function segmentFills(step: CalibrationStepView): SegmentFill[] {
  const total = Math.max(1, Math.floor(step.segments_total) || 1)
  const done = step.status === 'done'
  const progress = done ? 1 : clamp01(step.progress)
  return Array.from({ length: total }, (_, i) => {
    const fill = clamp01(progress * total - i)
    return {
      fill,
      tone: i % 2 === 0 ? 'tense' : 'relax',
      current: step.status === 'running' && fill > 0 && fill < 1,
    }
  })
}

/** Дорожки графика: сигналы шагов в порядке ЭЭГ, ЭМГ, левая, правая, без повторов. */
export function trackSignals(steps: readonly CalibrationStepView[]): string[] {
  const all = new Set(steps.flatMap((s) => s.signals))
  const known = TRACK_ORDER.filter((name) => all.delete(name))
  return [...known, ...all]
}

export const trackLabel = (signal: string): string => t.CALIB.trackNames[signal] ?? signal

/** Шаг, который калибрует сигнал (для кнопок «Перекалибровать …»). */
export const stepFor = (
  steps: readonly CalibrationStepView[],
  match: (signal: string) => boolean,
): CalibrationStepView | undefined => steps.find((s) => s.signals.some(match))

export type SensorTone = 'good' | 'warn' | 'bad' | 'muted'

export function sensorTone(sensor: SensorView): SensorTone {
  switch (sensor.state) {
    case 'connected':
    case 'ok':
    case 'live':
      return 'good'
    case 'connecting':
    case 'searching':
      return 'warn'
    case 'disconnected':
    case 'lost':
      return 'bad'
    default:
      return 'muted'
  }
}

/** «Датчик мышцы: подключён, 85 %» */
export function sensorText(sensor: SensorView): string {
  const name = t.CALIB.sensorNames[sensor.signal] ?? trackLabel(sensor.signal)
  const state = t.CALIB.sensorState[sensor.state] ?? sensor.state
  const battery =
    sensor.battery !== null && Number.isFinite(sensor.battery) ? `, ${Math.round(sensor.battery)} %` : ''
  return `${name}: ${state}${battery}`
}

// ---------- сигналы ----------

export interface Sample {
  t: number
  v: number
  ok: boolean
  r: string | null
}

export interface Burst {
  signal: string
  t: number
  rise: number
}

export interface SignalFrame {
  t: number
  signals: Record<string, { v: number; ok: boolean; r: string | null }>
  bursts: Burst[]
}

/** Текст причины недействительного значения по-русски; неизвестная причина — «нет данных». */
export function reasonText(reason: string | null | undefined): string {
  if (!reason) return t.REASON_UNKNOWN
  if (reason in t.REASONS) return t.REASONS[reason] as string
  const known = Object.values(t.REASONS)
  return known.includes(reason) ? reason : t.REASON_UNKNOWN
}

const isRecord = (x: unknown): x is Record<string, unknown> => typeof x === 'object' && x !== null && !Array.isArray(x)

function parseOne(raw: unknown): SignalFrame | null {
  if (!isRecord(raw) || typeof raw.t_ms !== 'number' || !Number.isFinite(raw.t_ms)) return null
  const signals: SignalFrame['signals'] = {}
  if (isRecord(raw.signals)) {
    for (const [name, value] of Object.entries(raw.signals)) {
      if (!isRecord(value) || typeof value.v !== 'number' || !Number.isFinite(value.v)) continue
      signals[name] = {
        v: clamp01(value.v),
        ok: value.ok !== false,
        r: typeof value.r === 'string' ? value.r : null,
      }
    }
  }
  const bursts: Burst[] = []
  if (Array.isArray(raw.bursts)) {
    for (const b of raw.bursts as unknown[]) {
      if (!isRecord(b) || typeof b.signal !== 'string' || typeof b.t_ms !== 'number') continue
      bursts.push({ signal: b.signal, t: b.t_ms, rise: typeof b.rise === 'number' ? b.rise : 0 })
    }
  }
  return { t: raw.t_ms, signals, bursts }
}

export interface SignalBatch {
  /** Поколение моста: меняется при перезапуске или переподключении, шкала `t_ms` начинается заново. */
  gen: number | null
  frames: SignalFrame[]
}

/** Разбор кадра SSE `/api/signals`: `{gen, samples:[…], bursts}`; мусор отбрасывается. */
export function parseBatch(data: string): SignalBatch {
  let raw: unknown
  try {
    raw = JSON.parse(data)
  } catch {
    return { gen: null, frames: [] }
  }
  const gen = isRecord(raw) && typeof raw.gen === 'number' ? raw.gen : null
  return { gen, frames: parseFrames(raw) }
}

/** Кадры из уже разобранного JSON: `{samples:[…]}` или одиночный отсчёт. */
export function parseFrames(raw: unknown): SignalFrame[] {
  if (isRecord(raw) && Array.isArray(raw.samples)) {
    const bursts = parseOne({ t_ms: 0, bursts: raw.bursts })?.bursts ?? []
    const frames = (raw.samples as unknown[]).flatMap((s) => parseOne(s) ?? [])
    const last = frames[frames.length - 1]
    if (last) last.bursts = [...last.bursts, ...bursts]
    else if (bursts.length > 0) return [{ t: 0, signals: {}, bursts }]
    return frames
  }
  const one = parseOne(raw)
  return one ? [one] : []
}

/** Кольцевой буфер фиксированной ёмкости: старые значения затираются новыми, без перевыделений. */
export class RingBuffer<T> {
  private readonly items: (T | undefined)[]
  private head = 0
  private count = 0
  readonly capacity: number

  constructor(capacity: number) {
    this.capacity = capacity
    this.items = new Array<T | undefined>(capacity)
  }

  get size(): number {
    return this.count
  }

  push(item: T): void {
    this.items[(this.head + this.count) % this.capacity] = item
    if (this.count < this.capacity) this.count += 1
    else this.head = (this.head + 1) % this.capacity
  }

  /** Содержимое от старого к новому. */
  toArray(): T[] {
    const out: T[] = []
    for (let i = 0; i < this.count; i += 1) out.push(this.items[(this.head + i) % this.capacity] as T)
    return out
  }

  clear(): void {
    this.head = 0
    this.count = 0
    this.items.fill(undefined)
  }
}

const SAMPLES_CAPACITY = 1500
const BURSTS_CAPACITY = 64
/** Если время кадра ушло назад дальше этого, мост перезапустился: прошлые значения не нужны. */
const REWIND_MS = 2000

/** Буферы сигналов вне состояния React: график читает их сам в каждом кадре отрисовки. */
export class SignalStore {
  private readonly samplesByName = new Map<string, RingBuffer<Sample>>()
  private readonly burstBuffer = new RingBuffer<Burst>(BURSTS_CAPACITY)
  /** Поколение моста последнего кадра; null — кадров ещё не было. */
  gen: number | null = null
  /** Время последнего отсчёта моста, мс; null — данных ещё не было. */
  lastT: number | null = null
  /** Когда он пришёл (`performance.now()`), мс: для плавного движения между кадрами. */
  lastAt = 0

  /** Принимает кадр SSE: при смене поколения моста буфер очищается, шкала времени началась заново. */
  apply(batch: SignalBatch, now: number): void {
    if (batch.gen !== null) {
      if (this.gen !== null && batch.gen !== this.gen) this.clear()
      this.gen = batch.gen
    }
    for (const frame of batch.frames) this.push(frame, now)
  }

  push(frame: SignalFrame, now: number): void {
    if (this.lastT !== null && frame.t < this.lastT - REWIND_MS) this.clear()
    for (const [name, value] of Object.entries(frame.signals)) {
      let buffer = this.samplesByName.get(name)
      if (!buffer) {
        buffer = new RingBuffer<Sample>(SAMPLES_CAPACITY)
        this.samplesByName.set(name, buffer)
      }
      buffer.push({ t: frame.t, v: value.v, ok: value.ok, r: value.r })
    }
    for (const burst of frame.bursts) this.burstBuffer.push(burst)
    if (Object.keys(frame.signals).length > 0 && (this.lastT === null || frame.t >= this.lastT)) {
      this.lastT = frame.t
      this.lastAt = now
    }
  }

  samples(signal: string): Sample[] {
    return this.samplesByName.get(signal)?.toArray() ?? []
  }

  bursts(): Burst[] {
    return this.burstBuffer.toArray()
  }

  /** Правый край окна: время последнего отсчёта плюс время, прошедшее с его прихода (не больше предела). */
  windowEnd(now: number): number | null {
    if (this.lastT === null) return null
    return this.lastT + Math.min(Math.max(0, now - this.lastAt), EXTRAPOLATE_MS)
  }

  clear(): void {
    this.samplesByName.clear()
    this.burstBuffer.clear()
    this.gen = null
    this.lastT = null
    this.lastAt = 0
  }
}

export interface Segment {
  ok: boolean
  /** Причина для серых участков (по-русски), у действительных null. */
  reason: string | null
  /** Индексы первого и последнего отсчёта участка во входном массиве. */
  start: number
  end: number
}

/** Разбивка на подряд идущие участки с одним `valid`; серые делятся ещё и по причине. */
export function splitValid(samples: readonly Sample[]): Segment[] {
  const out: Segment[] = []
  samples.forEach((sample, i) => {
    const reason = sample.ok ? null : reasonText(sample.r)
    const last = out[out.length - 1]
    if (last && last.ok === sample.ok && last.reason === reason) last.end = i
    else out.push({ ok: sample.ok, reason, start: i, end: i })
  })
  return out
}

/** Отсчёты, попавшие в окно, плюс один перед ним (чтобы линия начиналась от левого края). */
export function inWindow(samples: readonly Sample[], end: number, windowMs = WINDOW_MS): Sample[] {
  const from = end - windowMs
  const first = samples.findIndex((s) => s.t >= from)
  if (first < 0) return []
  return samples.slice(Math.max(0, first - 1))
}

/** Положение времени на оси x: левая граница окна — `left`, правая — `left + width`. */
export function timeToX(time: number, end: number, left: number, width: number, windowMs = WINDOW_MS): number {
  return left + ((time - (end - windowMs)) / windowMs) * width
}

/** Положение значения 0…1 на оси y дорожки: 1 — верх, 0 — низ. */
export function valueToY(value: number, top: number, height: number): number {
  return top + (1 - clamp01(value)) * height
}

/** Метки `burst`, попавшие в окно, для сигнала. */
export function burstsFor(bursts: readonly Burst[], signal: string, end: number, windowMs = WINDOW_MS): Burst[] {
  return bursts.filter((b) => b.signal === signal && b.t >= end - windowMs && b.t <= end)
}

/** Часть шага по сигналу; если ядро `parts` не прислало, берётся статус всего шага. */
export function partOf(step: CalibrationStepView, signal: string): CalibrationPartView {
  return (
    step.parts?.find((p) => p.signal === signal) ?? {
      signal,
      status: step.status,
      progress: step.progress,
      reason_text: step.reason_text,
    }
  )
}

/** Сигналы шага, чья часть не удалась (для «Повторить» по игроку). */
export const failedSignals = (step: CalibrationStepView): string[] =>
  step.signals.filter((s) => partOf(step, s).status === 'failed')
