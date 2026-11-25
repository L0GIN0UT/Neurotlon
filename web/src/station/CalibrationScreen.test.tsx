import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { baselineStep, calibrating, step } from './calibrationFixtures.ts'
import { StationApp } from './StationApp.tsx'
import type { CandidateView, Snapshot, StateView } from './types.ts'

class FakeEventSource {
  static all: FakeEventSource[] = []
  static readonly CLOSED = 2
  onopen: (() => void) | null = null
  onerror: (() => void) | null = null
  onmessage: ((event: MessageEvent<string>) => void) | null = null
  readyState = 1
  readonly url: string
  constructor(url: string) {
    this.url = url
    FakeEventSource.all.push(this)
  }
  close(): void {
    this.readyState = FakeEventSource.CLOSED
  }
  emitRaw(data: unknown): void {
    this.onmessage?.(new MessageEvent('message', { data: JSON.stringify(data) }))
  }
  static events(): FakeEventSource | undefined {
    return FakeEventSource.all.find((s) => s.url.includes('/api/events'))
  }
  static signals(): FakeEventSource[] {
    return FakeEventSource.all.filter((s) => s.url.includes('/api/signals'))
  }
}

const anna: CandidateView = {
  code: 'NT03',
  display_name: 'Анна',
  team: null,
  issues: [],
  offline: false,
  warned: false,
}
const boris: CandidateView = { ...anna, code: 'NT04', display_name: 'Борис' }

function snapshot(state: StateView, discipline = 'darts'): Snapshot {
  return {
    discipline,
    players_needed: discipline === 'pong' ? 2 : 1,
    status: { pending: 0, rejected: 0, online: true },
    state,
  }
}

const sent = (mock: ReturnType<typeof vi.fn>) =>
  mock.mock.calls.map((call) => JSON.parse((call[1] as RequestInit).body as string))

const pongSteps = (over = {}) => [
  step({ id: 'pong-cycle', signals: ['emg_left', 'emg_right'], ...over }),
]

async function show(state: StateView, discipline = 'darts') {
  render(<StationApp />)
  act(() => FakeEventSource.events()?.emitRaw(snapshot(state, discipline)))
  await screen.findByText('Калибровка датчиков')
}

describe('calibration screen', () => {
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    vi.stubGlobal('EventSource', FakeEventSource)
    fetchMock = vi.fn().mockResolvedValue({ ok: true })
    vi.stubGlobal('fetch', fetchMock)
    // jsdom не умеет рисовать: график получает «пустой» контекст и просто не рисует
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null)
    window.history.pushState({}, '', '/station.html?port=8799&token=abcdefgh')
  })
  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
    FakeEventSource.all = []
  })

  it('shows the tense phase big with the countdown and the segment bar', async () => {
    await show(
      calibrating({
        steps: [step({ status: 'running', phase: 'tense', phase_left_s: 3.4, progress: 0.1 }), baselineStep()],
      }),
    )
    expect(screen.getByText('НАПРЯГИТЕ')).toBeTruthy()
    expect(screen.getByTestId('countdown').textContent).toBe('4с')
    expect(document.querySelectorAll('.segment')).toHaveLength(4)
    expect(screen.getByText('НАПРЯГИТЕ').closest('[aria-live]')?.getAttribute('aria-live')).toBe('polite')
    expect(screen.getByText('Ожидает')).toBeTruthy()
    expect(screen.getByText('Датчик мышцы: подключён, 61 %')).toBeTruthy()
    expect(screen.getByText('Метод ЭЭГ: альфа')).toBeTruthy()
  })

  it('switches the word to relax', async () => {
    await show(calibrating({ steps: [step({ status: 'running', phase: 'relax', phase_left_s: 5 })] }))
    expect(screen.getByText('РАССЛАБЬТЕ')).toBeTruthy()
  })

  it('shows the dot, the instruction and the 12 s countdown for the brain step', async () => {
    await show(
      calibrating({
        steps: [step({ status: 'done' }), baselineStep({ status: 'running', progress: 0 })],
        current: 'eeg-baseline',
      }),
    )
    expect(screen.getByText('Смотрите на точку, глаза открыты')).toBeTruthy()
    expect(screen.getByTestId('countdown').textContent).toBe('12с')
    expect(document.querySelector('.baseline-dot')).toBeTruthy()
    expect(screen.getByText('Готово')).toBeTruthy()
  })

  it('does not subscribe to signals before the check and has no chart', async () => {
    await show(calibrating({ steps: [step({ status: 'running', phase: 'tense' })] }))
    expect(FakeEventSource.signals()).toHaveLength(0)
    expect(document.querySelector('canvas')).toBeNull()
  })

  it('offers the check with the chart, tips and all four buttons when ready', async () => {
    await show(calibrating({ steps: [step({ status: 'done' }), baselineStep({ status: 'done' })], ready: true }))
    expect(screen.getByText('Проверка сигнала')).toBeTruthy()
    expect(screen.getByRole('img', { name: 'Проверка сигнала' }).tagName).toBe('CANVAS')
    expect(screen.getByText('Резко напрягите мышцу с датчиком: должна появиться отметка')).toBeTruthy()
    expect(screen.getByText('Расслабьтесь: линия мозга растёт')).toBeTruthy()
    const primary = screen.getByRole('button', { name: 'Дальше к игре' })
    expect(document.activeElement).toBe(primary)

    fireEvent.click(screen.getByRole('button', { name: 'Перекалибровать мышцу' }))
    fireEvent.click(screen.getByRole('button', { name: 'Перекалибровать мозг' }))
    fireEvent.click(screen.getByRole('button', { name: 'Назад' }))
    fireEvent.click(primary)
    expect(sent(fetchMock)).toEqual([
      { action: 'calibration_retry', value: 'emg-cycle' },
      { action: 'calibration_retry', value: 'eeg-baseline' },
      { action: 'back' },
      { action: 'calibration_continue' },
    ])
  })

  it('reads the signals only while the check is open, with the same token, and closes the stream', async () => {
    render(<StationApp />)
    act(() =>
      FakeEventSource.events()?.emitRaw(
        snapshot(calibrating({ steps: [step({ status: 'done' }), baselineStep({ status: 'done' })], ready: true })),
      ),
    )
    await screen.findByText('Проверка сигнала')
    const [stream] = FakeEventSource.signals()
    expect(stream?.url).toBe('http://127.0.0.1:8799/api/signals?token=abcdefgh')
    act(() =>
      stream?.emitRaw({
        t_ms: 1000,
        signals: { emg: { v: 0.4, ok: true, r: null }, eeg: { v: 0.1, ok: false, r: 'artifact' } },
        bursts: [{ signal: 'emg', t_ms: 990, rise: 0.3 }],
      }),
    )
    act(() =>
      FakeEventSource.events()?.emitRaw(
        snapshot({ kind: 'playing', players: [anna], offline: false, default_limit: false }),
      ),
    )
    await screen.findByText('Идёт игра')
    await vi.waitFor(() => expect(stream?.readyState).toBe(FakeEventSource.CLOSED))
  })

  it('reopens the signal stream after it was closed by an error', async () => {
    vi.useFakeTimers()
    try {
      render(<StationApp />)
      act(() =>
        FakeEventSource.events()?.emitRaw(
          snapshot(calibrating({ steps: [step({ status: 'done' })], ready: true })),
        ),
      )
      const first = FakeEventSource.signals()[0]
      expect(first).toBeTruthy()
      act(() => {
        if (first) first.readyState = FakeEventSource.CLOSED
        first?.onerror?.()
      })
      act(() => {
        vi.advanceTimersByTime(1100)
      })
      expect(FakeEventSource.signals()).toHaveLength(2)
    } finally {
      vi.useRealTimers()
    }
  })

  it('shows a failed step in red with the reason and retries it', async () => {
    await show(
      calibrating({
        steps: [step({ status: 'failed', reason_text: 'датчик отключён' }), baselineStep()],
      }),
    )
    expect(screen.getAllByText('датчик отключён').length).toBeGreaterThan(0)
    expect(document.querySelector('.step-card-failed')).toBeTruthy()
    expect(screen.getByRole('alert').textContent).toContain('Калибровка не удалась')
    // «Повторить» есть и на красной карточке слева, и в центре: оба шлют id шага
    const retries = screen.getAllByRole('button', { name: 'Повторить' })
    expect(retries).toHaveLength(2)
    retries.forEach((button) => fireEvent.click(button))
    expect(sent(fetchMock)).toEqual([
      { action: 'calibration_retry', value: 'emg-cycle' },
      { action: 'calibration_retry', value: 'emg-cycle' },
    ])
  })

  it('says the bridge does not answer and offers retry and back', async () => {
    await show(calibrating({ link: 'lost', steps: [step({ status: 'running' })] }))
    expect(screen.getAllByText('Мост датчиков не отвечает').length).toBeGreaterThan(0)
    fireEvent.click(screen.getByRole('button', { name: 'Повторить' }))
    fireEvent.click(screen.getByRole('button', { name: 'Назад' }))
    expect(sent(fetchMock)).toEqual([{ action: 'calibration_restart' }, { action: 'back' }])
  })

  it('shows a spinner while the bridge has not sent the steps yet', async () => {
    await show(calibrating({ link: 'connecting', steps: [], current: null }))
    expect(screen.getByText('Подключаем мост датчиков…')).toBeTruthy()
  })

  it('shows both pong players with their names and sides', async () => {
    await show(
      calibrating({
        players: [anna, boris],
        sensors: [
          { signal: 'emg_left', state: 'connected', battery: 90 },
          { signal: 'emg_right', state: 'connected', battery: 80 },
        ],
        eeg_method: null,
        steps: pongSteps({ status: 'running', phase: 'tense', phase_left_s: 2 }),
        current: 'pong-cycle',
      }),
      'pong',
    )
    expect(screen.getByText('Анна')).toBeTruthy()
    expect(screen.getByText('Борис')).toBeTruthy()
    expect(screen.getByText('Игрок 1 · слева')).toBeTruthy()
    expect(screen.getByText('Игрок 2 · справа')).toBeTruthy()
    expect(screen.getByText('Мышцы игроков')).toBeTruthy()
    expect(screen.queryByText(/Метод ЭЭГ/)).toBeNull()
  })

  it('offers a retry only for the pong player whose part failed', async () => {
    await show(
      calibrating({
        players: [anna, boris],
        eeg_method: null,
        steps: pongSteps({
          status: 'failed',
          reason_text: 'нет контакта',
          parts: [
            { signal: 'emg_left', status: 'done', progress: 1, reason_text: null },
            { signal: 'emg_right', status: 'failed', progress: 0.5, reason_text: 'нет контакта' },
          ],
        }),
        current: 'pong-cycle',
      }),
      'pong',
    )
    expect(screen.queryByRole('button', { name: 'Повторить: игрок 1' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Повторить: игрок 2' }))
    expect(sent(fetchMock)).toEqual([{ action: 'calibration_retry', value: 'emg_right' }])
  })

  it('clears the chart when the bridge generation changes', async () => {
    render(<StationApp />)
    act(() =>
      FakeEventSource.events()?.emitRaw(
        snapshot(calibrating({ steps: [step({ status: 'done' })], ready: true })),
      ),
    )
    await screen.findByText('Проверка сигнала')
    const [stream] = FakeEventSource.signals()
    const frame = (gen: number, t: number) => ({
      gen,
      samples: [{ t_ms: t, signals: { emg: { v: 0.4, ok: true } } }],
      bursts: [],
    })
    act(() => stream?.emitRaw(frame(1, 500_000)))
    act(() => stream?.emitRaw(frame(2, 100)))
    expect(stream?.readyState).toBe(1)
  })

  it('recalibrates each pong player separately and has no brain button', async () => {
    await show(
      calibrating({
        players: [anna, boris],
        eeg_method: null,
        steps: pongSteps({ status: 'done' }),
        current: 'pong-cycle',
        ready: true,
      }),
      'pong',
    )
    fireEvent.click(screen.getByRole('button', { name: 'Повторить: игрок 1' }))
    fireEvent.click(screen.getByRole('button', { name: 'Повторить: игрок 2' }))
    expect(screen.queryByRole('button', { name: 'Перекалибровать мозг' })).toBeNull()
    expect(sent(fetchMock)).toEqual([
      { action: 'calibration_retry', value: 'emg_left' },
      { action: 'calibration_retry', value: 'emg_right' },
    ])
  })

  it('maps Enter and Escape: Enter only when ready', async () => {
    await show(calibrating({ steps: [step({ status: 'running', phase: 'tense' })] }))
    fireEvent.keyDown(window, { key: 'Enter' })
    expect(sent(fetchMock)).toEqual([])
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(sent(fetchMock)).toEqual([{ action: 'back' }])

    act(() =>
      FakeEventSource.events()?.emitRaw(
        snapshot(calibrating({ steps: [step({ status: 'done' }), baselineStep({ status: 'done' })], ready: true })),
      ),
    )
    await screen.findByText('Проверка сигнала')
    fireEvent.keyDown(window, { key: 'Enter' })
    expect(sent(fetchMock).at(-1)).toEqual({ action: 'calibration_continue' })
  })

  it('does not turn Enter on a secondary button into "continue"', async () => {
    await show(calibrating({ steps: [step({ status: 'done' }), baselineStep({ status: 'done' })], ready: true }))
    const secondary = screen.getByRole('button', { name: 'Перекалибровать мышцу' })
    secondary.focus()
    fireEvent.keyDown(secondary, { key: 'Enter' })
    expect(sent(fetchMock)).toEqual([])
  })

  it('moves the step bar to Calibration and counts the result as the fifth step', async () => {
    await show(calibrating({ steps: [step({ status: 'running' })] }))
    const bar = screen.getByRole('list', { name: 'Шаги' })
    expect(bar.querySelectorAll('li')).toHaveLength(5)
    expect(bar.querySelector('[aria-current="step"]')?.textContent).toContain('Калибровка')
    act(() =>
      FakeEventSource.events()?.emitRaw(
        snapshot({ kind: 'done', lines: ['NT03: 8 очк.'], seconds_left: 5, seconds_total: 5 }),
      ),
    )
    await screen.findByText('Готово!')
    expect(bar.querySelector('[aria-current="step"]')?.textContent).toContain('Результат')
  })
})
