import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { StationApp } from './StationApp.tsx'
import type { CandidateView, Snapshot, StateView } from './types.ts'

class FakeEventSource {
  static last: FakeEventSource | null = null
  static readonly CLOSED = 2
  onopen: (() => void) | null = null
  onerror: (() => void) | null = null
  onmessage: ((event: MessageEvent<string>) => void) | null = null
  readyState = 1
  readonly url: string
  constructor(url: string) {
    this.url = url
    FakeEventSource.last = this
  }
  close(): void {
    this.readyState = FakeEventSource.CLOSED
  }
  emit(snapshot: Snapshot): void {
    this.onmessage?.(new MessageEvent('message', { data: JSON.stringify(snapshot) }))
  }
}

const anna: CandidateView = {
  code: 'NT03',
  display_name: 'Анна',
  team: { number: 1, name: 'Красные', color: '#e5484d' },
  issues: ['no_pair_assigned'],
  offline: false,
  warned: true,
}

function snapshot(state: StateView, discipline = 'darts'): Snapshot {
  return {
    discipline,
    players_needed: discipline === 'pong' ? 2 : 1,
    status: { pending: 0, rejected: 0, online: true },
    state,
  }
}

const SCREENS: [string, StateView, string][] = [
  ['scan', { kind: 'idle', input: '', notice: 'Нет такого ID', taken: [] }, 'Нет такого ID'],
  ['checking', { kind: 'checking', code: 'NT03', taken: [] }, 'Проверяем участника…'],
  [
    'confirm',
    { kind: 'confirm', candidate: anna, taken: [], notice: null, is_last: true },
    'Не назначена пара',
  ],
  ['starting', { kind: 'starting', players: [anna] }, 'Запускаем игру…'],
  [
    'playing',
    { kind: 'playing', players: [anna], offline: true, default_limit: true },
    'Идёт игра',
  ],
  ['done', { kind: 'done', lines: ['NT03: 8 очк.'], seconds_left: 5, seconds_total: 5 }, 'Готово!'],
  ['problem', { kind: 'problem', reason: 'Игра упала', players: [anna] }, 'Игра упала'],
  ['blocked', { kind: 'blocked', message: 'Не та дисциплина' }, 'Не та дисциплина'],
  [
    'rejected',
    { kind: 'rejected', items: [{ session_id: '7b1d3e005a4f', codes: ['NT03'], error: 'conflict' }], exported_to: null },
    'conflict',
  ],
]

describe('StationApp', () => {
  beforeEach(() => {
    vi.stubGlobal('EventSource', FakeEventSource)
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true }))
    window.history.pushState({}, '', '/station.html?port=8799&token=abcdefgh')
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    FakeEventSource.last = null
  })

  it('explains itself when opened without a launcher', () => {
    window.history.pushState({}, '', '/station.html')
    render(<StationApp />)
    expect(screen.getByText(/без лаунчера/)).toBeTruthy()
  })

  it.each(SCREENS)('renders the %s screen', async (_name, state, text) => {
    render(<StationApp />)
    act(() => FakeEventSource.last?.emit(snapshot(state)))
    expect(await screen.findByText(text)).toBeTruthy()
  })

  it('sends the typed digit and the Play command', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true })
    vi.stubGlobal('fetch', fetchMock)
    render(<StationApp />)
    act(() =>
      FakeEventSource.last?.emit(snapshot({ kind: 'idle', input: '', notice: null, taken: [] })),
    )
    fireEvent.click(await screen.findByRole('button', { name: '7' }))
    const sent = () => fetchMock.mock.calls.map((call) => JSON.parse((call[1] as RequestInit).body as string))
    expect(sent()).toContainEqual({ action: 'type_char', value: '7' })

    act(() =>
      FakeEventSource.last?.emit(
        snapshot({ kind: 'confirm', candidate: anna, taken: [], notice: null, is_last: true }),
      ),
    )
    fireEvent.click(await screen.findByTestId('play'))
    expect(sent()).toContainEqual({ action: 'confirm' })
  })

  it('shows the pong slots and who is expected next', async () => {
    render(<StationApp />)
    act(() =>
      FakeEventSource.last?.emit(
        snapshot({ kind: 'idle', input: '', notice: null, taken: [anna] }, 'pong'),
      ),
    )
    expect(await screen.findByText('Игрок 2: покажите QR-код бейджа')).toBeTruthy()
    expect(screen.getByText('Анна')).toBeTruthy()
  })

  it('maps the keyboard to commands', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true })
    vi.stubGlobal('fetch', fetchMock)
    render(<StationApp />)
    act(() =>
      FakeEventSource.last?.emit(snapshot({ kind: 'idle', input: '', notice: null, taken: [] })),
    )
    await screen.findByTestId('id-field')
    fireEvent.keyDown(window, { key: '4' })
    fireEvent.keyDown(window, { key: 'Enter' })
    const actions = fetchMock.mock.calls.map((call) => JSON.parse((call[1] as RequestInit).body as string).action)
    expect(actions).toEqual(['type_char', 'submit_input'])
  })

  it('warns when the launcher link is lost', async () => {
    render(<StationApp />)
    act(() => {
      const source = FakeEventSource.last
      if (source) {
        source.readyState = FakeEventSource.CLOSED
        source.onerror?.()
      }
    })
    expect(await screen.findByText('Нет связи с лаунчером')).toBeTruthy()
  })
})
