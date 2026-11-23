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

  describe('setup', () => {
    const setup = (
      phase: 'form' | 'checking' | 'ok' | 'saved',
      extra: { error?: string | null; discipline?: string | null } = {},
    ): Snapshot =>
      snapshot({
        kind: 'setup',
        phase,
        error: extra.error ?? null,
        discipline: extra.discipline ?? null,
        players_needed: extra.discipline === 'pong' ? 2 : extra.discipline ? 1 : null,
        form: {
          server_url: 'https://192.168.1.10',
          game_path: '',
          ca_file: '',
          camera: '',
          sensors: '',
          devices: {},
        },
        has_token: false,
        sensors_available: false,
        roles: [],
        scan: { phase: 'idle', devices: [], error: null },
      }, '')

    const sentActions = (fetchMock: ReturnType<typeof vi.fn>) =>
      fetchMock.mock.calls.map((call) => JSON.parse((call[1] as RequestInit).body as string))

    it('checks the typed fields, then saves only the checked ones', async () => {
      const fetchMock = vi.fn().mockResolvedValue({ ok: true })
      vi.stubGlobal('fetch', fetchMock)
      render(<StationApp />)
      act(() => FakeEventSource.last?.emit(setup('form')))
      const token = await screen.findByLabelText(/Токен станции/)
      fireEvent.change(token, { target: { value: 'secret-token-0123456789' } })
      fireEvent.change(screen.getByLabelText(/Игра/), { target: { value: 'C:/g/Darts.exe' } })
      const save = screen.getByRole('button', { name: /Сохранить и запустить/ })
      expect((save as HTMLButtonElement).disabled).toBe(true)

      fireEvent.click(screen.getByRole('button', { name: 'Проверить подключение' }))
      expect(sentActions(fetchMock)).toContainEqual({
        action: 'setup_check',
        value: {
          server_url: 'https://192.168.1.10',
          token: 'secret-token-0123456789',
          game_path: 'C:/g/Darts.exe',
          ca_file: '',
          camera: '',
          sensors: '',
          devices: {},
        },
      })

      act(() => FakeEventSource.last?.emit(setup('ok', { discipline: 'pong' })))
      expect(await screen.findByTestId('setup-ok')).toBeTruthy()
      expect(screen.getByText(/Понг/).textContent).toContain('2 игрока')
      expect((save as HTMLButtonElement).disabled).toBe(false)
      fireEvent.click(save)
      expect(sentActions(fetchMock).at(-1)?.action).toBe('setup_save')
    })

    it('drops the green light when a field changes after the check', async () => {
      render(<StationApp />)
      act(() => FakeEventSource.last?.emit(setup('form')))
      fireEvent.change(await screen.findByLabelText(/Токен станции/), {
        target: { value: 'secret-token-0123456789' },
      })
      fireEvent.click(screen.getByRole('button', { name: 'Проверить подключение' }))
      act(() => FakeEventSource.last?.emit(setup('ok', { discipline: 'darts' })))
      const save = await screen.findByRole('button', { name: /Сохранить и запустить/ })
      expect((save as HTMLButtonElement).disabled).toBe(false)
      fireEvent.change(screen.getByLabelText(/Адрес сервера/), { target: { value: 'https://other' } })
      expect((save as HTMLButtonElement).disabled).toBe(true)
      expect(screen.queryByTestId('setup-ok')).toBeNull()
    })

    it('shows why the check failed', async () => {
      render(<StationApp />)
      act(() => FakeEventSource.last?.emit(setup('form', { error: 'Токен не подходит' })))
      expect(await screen.findByText('Токен не подходит')).toBeTruthy()
    })

    it('never types digits from the keyboard into the badge field', async () => {
      const fetchMock = vi.fn().mockResolvedValue({ ok: true })
      vi.stubGlobal('fetch', fetchMock)
      render(<StationApp />)
      act(() => FakeEventSource.last?.emit(setup('form')))
      await screen.findByLabelText(/Токен станции/)
      fireEvent.keyDown(window, { key: '7' })
      expect(sentActions(fetchMock)).toEqual([])
    })
  })

  describe('camera choice', () => {
    const devices = [
      { kind: 'videoinput', deviceId: 'a1', label: 'Integrated Camera' },
      { kind: 'videoinput', deviceId: 'b2', label: 'USB Webcam' },
      { kind: 'audioinput', deviceId: 'm1', label: 'Mic' },
    ]
    const stubMedia = () => {
      const stream = { getTracks: () => [{ stop: vi.fn() }] }
      const getUserMedia = vi.fn().mockResolvedValue(stream)
      vi.stubGlobal('navigator', {
        ...navigator,
        mediaDevices: { getUserMedia, enumerateDevices: vi.fn().mockResolvedValue(devices) },
      })
      return getUserMedia
    }

    it('offers the connected cameras and saves the chosen one with the form', async () => {
      stubMedia()
      const fetchMock = vi.fn().mockResolvedValue({ ok: true })
      vi.stubGlobal('fetch', fetchMock)
      render(<StationApp />)
      act(() =>
        FakeEventSource.last?.emit(
          snapshot(
            {
              kind: 'setup',
              phase: 'form',
              error: null,
              discipline: null,
              players_needed: null,
              form: {
                server_url: 'https://h',
                game_path: '',
                ca_file: '',
                camera: '',
                sensors: '',
                devices: {},
              },
              has_token: false,
              sensors_available: false,
              roles: [],
              scan: { phase: 'idle', devices: [], error: null },
            },
            '',
          ),
        ),
      )
      const select = (await screen.findByLabelText('Камера для QR')) as HTMLSelectElement
      await screen.findByRole('option', { name: 'USB Webcam' })
      expect([...select.options].map((o) => o.textContent)).toEqual([
        'По умолчанию',
        'Integrated Camera',
        'USB Webcam',
      ])
      fireEvent.change(select, { target: { value: 'USB Webcam' } })
      fireEvent.click(screen.getByRole('button', { name: 'Проверить подключение' }))
      const sent = fetchMock.mock.calls.map((call) => JSON.parse((call[1] as RequestInit).body as string))
      expect(sent.at(-1).value.camera).toBe('USB Webcam')
    })

    it('opens the camera saved in the settings by its name', async () => {
      const getUserMedia = stubMedia()
      render(<StationApp />)
      act(() =>
        FakeEventSource.last?.emit({
          ...snapshot({ kind: 'idle', input: '', notice: null, taken: [] }),
          camera: 'USB Webcam',
        }),
      )
      await screen.findByTestId('id-field')
      await vi.waitFor(() => {
        const used = getUserMedia.mock.calls.map((call) => call[0])
        expect(used).toContainEqual(
          expect.objectContaining({ video: expect.objectContaining({ deviceId: { exact: 'b2' } }) }),
        )
      })
    })

    it('shows the NT prefix before typed digits only', async () => {
      render(<StationApp />)
      act(() =>
        FakeEventSource.last?.emit(snapshot({ kind: 'idle', input: '7', notice: null, taken: [] })),
      )
      expect((await screen.findByTestId('id-field')).textContent).toContain('NT7')
      act(() =>
        FakeEventSource.last?.emit(snapshot({ kind: 'idle', input: 'NT0', notice: null, taken: [] })),
      )
      await vi.waitFor(() =>
        expect(screen.getByTestId('id-field').textContent).not.toContain('NTNT'),
      )
    })
  })

  describe('sensors', () => {
    const withSensors = (
      overrides: Partial<{
        roles: string[]
        discipline: string | null
        scan: { phase: 'idle' | 'scanning' | 'done'; devices: object[]; error: string | null }
        mode: string
        devices: Record<string, string>
        available: boolean
      }> = {},
    ): Snapshot =>
      snapshot(
        {
          kind: 'setup',
          phase: 'form',
          error: null,
          discipline: overrides.discipline ?? null,
          players_needed: null,
          form: {
            server_url: 'https://h',
            game_path: 'C:/g.exe',
            ca_file: '',
            camera: '',
            sensors: overrides.mode ?? 'hardware',
            devices: overrides.devices ?? {},
          },
          has_token: false,
          sensors_available: overrides.available ?? true,
          roles: overrides.roles ?? [],
          scan: (overrides.scan ?? { phase: 'idle', devices: [], error: null }) as never,
        },
        '',
      )

    const lastBody = (mock: ReturnType<typeof vi.fn>) => {
      const call = mock.mock.calls.at(-1)
      if (!call) throw new Error('no request was sent')
      return JSON.parse((call[1] as RequestInit).body as string)
    }

    it('is hidden when the build has no bridge', async () => {
      render(<StationApp />)
      act(() => FakeEventSource.last?.emit(withSensors({ available: false })))
      await screen.findByLabelText(/Токен станции/)
      expect(screen.queryByLabelText('Датчики')).toBeNull()
    })

    it('asks for a check first, then shows one serial field per role', async () => {
      render(<StationApp />)
      act(() => FakeEventSource.last?.emit(withSensors()))
      expect(await screen.findByText(/станция сообщит, какие датчики нужны/)).toBeTruthy()
      act(() => FakeEventSource.last?.emit(withSensors({ roles: ['emg_left', 'emg_right'], discipline: 'pong' })))
      expect(await screen.findByText('Левая рука (Callibri)')).toBeTruthy()
      expect(screen.getByText('Правая рука (Callibri)')).toBeTruthy()
    })

    it('scans on request and lists the devices with their serials', async () => {
      const fetchMock = vi.fn().mockResolvedValue({ ok: true })
      vi.stubGlobal('fetch', fetchMock)
      render(<StationApp />)
      act(() => FakeEventSource.last?.emit(withSensors({ roles: ['eeg', 'emg'], discipline: 'darts' })))
      fireEvent.click(await screen.findByRole('button', { name: 'Найти датчики' }))
      expect(lastBody(fetchMock)).toEqual({ action: 'sensors_scan' })
      act(() =>
        FakeEventSource.last?.emit(
          withSensors({
            roles: ['eeg', 'emg'],
            discipline: 'darts',
            scan: {
              phase: 'done',
              error: null,
              devices: [
                { kind: 'brainbit', name: 'BrainBit', serial: 'BB-777', address: 'AA:01' },
                { kind: 'callibri', name: 'Callibri', serial: '', address: 'AA:02' },
              ],
            },
          }),
        ),
      )
      const found = await screen.findByTestId('sensors-found')
      expect(found.textContent).toContain('BB-777')
      expect(found.textContent).toContain('серийный номер неизвестен')
    })

    it('sends the serials typed for each role with the check', async () => {
      const fetchMock = vi.fn().mockResolvedValue({ ok: true })
      vi.stubGlobal('fetch', fetchMock)
      render(<StationApp />)
      act(() => FakeEventSource.last?.emit(withSensors({ roles: ['eeg', 'emg'], discipline: 'darts' })))
      const inputs = await screen.findAllByPlaceholderText('Серийный номер')
      fireEvent.change(inputs[0] as HTMLElement, { target: { value: 'BB-777' } })
      fireEvent.change(inputs[1] as HTMLElement, { target: { value: 'CA-1' } })
      fireEvent.change(screen.getByLabelText(/Токен станции/), { target: { value: 'secret-token-0123456789' } })
      fireEvent.click(screen.getByRole('button', { name: 'Проверить подключение' }))
      const sent = lastBody(fetchMock)
      expect(sent.value.sensors).toBe('hardware')
      expect(sent.value.devices).toEqual({ eeg: 'BB-777', emg: 'CA-1' })
    })

    it('hides serials and scanning for the emulator', async () => {
      render(<StationApp />)
      act(() => FakeEventSource.last?.emit(withSensors({ mode: 'emulate', roles: ['eeg', 'emg'], discipline: 'darts' })))
      await screen.findByLabelText('Датчики')
      expect(screen.queryByRole('button', { name: 'Найти датчики' })).toBeNull()
    })

    it('warns in the top bar when the bridge is down, and only then', async () => {
      render(<StationApp />)
      act(() =>
        FakeEventSource.last?.emit({
          ...snapshot({ kind: 'idle', input: '', notice: null, taken: [] }),
          sensors: { mode: 'hardware', ok: false, error: 'Ошибка: нет Bluetooth-адаптера' },
        }),
      )
      expect(await screen.findByText('Датчики не подключены')).toBeTruthy()
      act(() =>
        FakeEventSource.last?.emit({
          ...snapshot({ kind: 'idle', input: '', notice: null, taken: [] }),
          sensors: { mode: 'hardware', ok: true, error: null },
        }),
      )
      await vi.waitFor(() => expect(screen.queryByText('Датчики не подключены')).toBeNull())
    })
  })
})
