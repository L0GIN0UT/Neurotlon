import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { SensorList } from './SensorList.tsx'
import { rssiBars } from './sensorModel.ts'
import type { SensorEntry, SensorsView } from './types.ts'

const entry = (over: Partial<SensorEntry>): SensorEntry => ({
  error: null,
  id: 'AA:01',
  name: 'BrainBit',
  kind: 'brainbit',
  serial: 'BB-777',
  address: 'AA:01',
  rssi: -60,
  in_range: true,
  age_s: 0,
  role: null,
  link: null,
  battery: null,
  contact: null,
  signal: null,
  level: null,
  ...over,
})

const callibri = (over: Partial<SensorEntry> = {}) =>
  entry({ id: 'AA:02', name: 'Callibri', kind: 'callibri', serial: null, address: 'AA:02', rssi: -80, ...over })

const view = (phase: SensorsView['phase'], devices: SensorEntry[], error: string | null = null): SensorsView => ({
  phase,
  error,
  devices,
})

const DARTS = ['eeg', 'emg']
const PONG = ['emg_left', 'emg_right']

afterEach(cleanup)

describe('SensorList', () => {
  it('shows the live header with a counter while scanning', () => {
    const devices = [entry({}), callibri(), entry({ id: 'AA:03', address: 'AA:03', name: 'BrainBit 2' })]
    render(<SensorList sensors={view('scanning', devices)} roles={DARTS} send={vi.fn()} />)
    expect(screen.getByTestId('sensors-count').textContent).toBe('найдено 3')
    expect(screen.getByTestId('sensors-count').getAttribute('aria-live')).toBe('polite')
    expect(screen.getByRole('button', { name: 'Остановить' })).toBeTruthy()
    expect(screen.getByText(/Поиск…/)).toBeTruthy()
  })

  it('lists a Callibri without a serial number and has no serial input', () => {
    render(<SensorList sensors={view('scanning', [entry({}), callibri()])} roles={DARTS} send={vi.fn()} />)
    const rows = screen.getAllByTestId('sensor-found')
    expect(rows).toHaveLength(2)
    expect(rows[1]?.textContent).toContain('номер после подключения')
    expect(rows[1]?.textContent).toContain('AA:02')
    expect(screen.queryByRole('textbox')).toBeNull()
    expect(screen.queryByPlaceholderText('Серийный номер')).toBeNull()
  })

  it('keeps the order of the core and does not sort by signal', () => {
    const devices = [entry({ id: 'A', address: 'A', rssi: -90 }), entry({ id: 'B', address: 'B', rssi: -40 })]
    render(<SensorList sensors={view('scanning', devices)} roles={DARTS} send={vi.fn()} />)
    const rows = screen.getAllByTestId('sensor-found')
    expect(rows[0]?.textContent).toContain('A')
    expect(rows[1]?.textContent).toContain('B')
  })

  it('describes signal strength in text for screen readers', () => {
    render(<SensorList sensors={view('scanning', [entry({ rssi: -60 })])} roles={DARTS} send={vi.fn()} />)
    expect(screen.getByRole('img', { name: 'Уровень приёма 3 из 4 (-60 дБм)' })).toBeTruthy()
    expect(rssiBars(null)).toBe(0)
    expect(rssiBars(-50)).toBe(4)
    expect(rssiBars(-90)).toBe(1)
  })

  it('dims devices that are out of the air and tells for how long', () => {
    render(<SensorList sensors={view('scanning', [entry({ in_range: false, age_s: 20 })])} roles={DARTS} send={vi.fn()} />)
    const row = screen.getByTestId('sensor-found')
    expect(row.className).toContain('stale')
    expect(row.textContent).toContain('нет в эфире 20 с')
    expect(within(row).queryByRole('img')).toBeNull()
  })

  it('assigns at once when there is a single free role of the right family', () => {
    const send = vi.fn()
    render(<SensorList sensors={view('scanning', [entry({}), callibri()])} roles={DARTS} send={send} />)
    const rows = screen.getAllByTestId('sensor-found')
    fireEvent.click(within(rows[1] as HTMLElement).getByRole('button', { name: 'Подключить' }))
    expect(send).toHaveBeenCalledWith({ action: 'sensors_assign', value: { role: 'emg', id: 'AA:02' } })
  })

  it('offers a role menu in pong and reaches it from the keyboard', () => {
    const send = vi.fn()
    render(<SensorList sensors={view('scanning', [callibri()])} roles={PONG} send={send} />)
    const button = screen.getByRole('button', { name: 'Подключить' })
    expect(button.getAttribute('aria-haspopup')).toBe('menu')
    fireEvent.click(button)
    const items = screen.getAllByRole('menuitem')
    expect(items.map((i) => i.textContent)).toEqual(['Датчик игрока 1 (слева)', 'Датчик игрока 2 (справа)'])
    expect(document.activeElement).toBe(items[0])
    fireEvent.keyDown(items[0] as HTMLElement, { key: 'ArrowDown' })
    expect(document.activeElement).toBe(items[1])
    fireEvent.click(items[1] as HTMLElement)
    expect(send).toHaveBeenCalledWith({ action: 'sensors_assign', value: { role: 'emg_right', id: 'AA:02' } })
    expect(screen.queryByRole('menu')).toBeNull()
  })

  it('closes the role menu with Escape and returns focus to the button', () => {
    render(<SensorList sensors={view('scanning', [callibri()])} roles={PONG} send={vi.fn()} />)
    const button = screen.getByRole('button', { name: 'Подключить' })
    fireEvent.click(button)
    fireEvent.keyDown(screen.getAllByRole('menuitem')[0] as HTMLElement, { key: 'Escape' })
    expect(screen.queryByRole('menu')).toBeNull()
    expect(document.activeElement).toBe(button)
  })

  it('shows only free pong roles in the menu', () => {
    const left = callibri({ id: 'AA:09', address: 'AA:09', role: 'emg_left', link: 'connected', signal: true })
    render(<SensorList sensors={view('scanning', [left, callibri()])} roles={PONG} send={vi.fn()} />)
    const row = screen.getByTestId('sensor-found')
    // единственная свободная роль: без меню
    expect(within(row).getByRole('button', { name: 'Подключить' }).getAttribute('aria-haspopup')).toBeNull()
  })

  it('does not offer a button for a family the station does not need', () => {
    render(<SensorList sensors={view('scanning', [entry({})])} roles={PONG} send={vi.fn()} />)
    const row = screen.getByTestId('sensor-found')
    expect(within(row).queryByRole('button')).toBeNull()
    expect(row.textContent).toContain('не нужен этой станции')
  })

  it('shows the found devices at once and disables connecting until the roles are known', () => {
    render(<SensorList sensors={view('scanning', [entry({})])} roles={[]} rolesKnown={false} send={vi.fn()} />)
    expect(screen.getAllByTestId('sensor-found')).toHaveLength(1)
    const button = screen.getByRole('button', { name: 'Подключить' }) as HTMLButtonElement
    expect(button.disabled).toBe(true)
    expect(button.title).toContain('Введите токен станции')
    expect(screen.getAllByText(/Введите токен станции: станет понятно, какие датчики нужны/).length).toBeGreaterThan(0)
  })

  it('treats an old launcher without roles_known as known when it sent roles', () => {
    render(<SensorList sensors={view('scanning', [entry({})])} roles={DARTS} send={vi.fn()} />)
    expect((screen.getByRole('button', { name: 'Подключить' }) as HTMLButtonElement).disabled).toBe(false)
    expect(screen.queryByText(/Введите токен станции/)).toBeNull()
  })

  it('offers connecting as before once the roles are known', () => {
    render(<SensorList sensors={view('scanning', [entry({})])} roles={DARTS} rolesKnown send={vi.fn()} />)
    expect((screen.getByRole('button', { name: 'Подключить' }) as HTMLButtonElement).disabled).toBe(false)
  })

  it('shows assigned roles with status text, battery and a muscle level bar', () => {
    const emg = callibri({ role: 'emg', link: 'connected', signal: true, battery: 80, level: 0.4, serial: 'CA-1' })
    const eeg = entry({ role: 'eeg', link: 'connecting' })
    render(<SensorList sensors={view('scanning', [eeg, emg])} roles={DARTS} send={vi.fn()} />)
    const emgRow = screen.getByTestId('role-emg')
    expect(within(emgRow).getByText('Сигнал есть')).toBeTruthy()
    expect(within(emgRow).getByText('Заряд 80%')).toBeTruthy()
    expect(within(emgRow).getByRole('meter', { name: 'Уровень сигнала мышцы' }).getAttribute('aria-valuenow')).toBe('40')
    expect(emgRow.textContent).toContain('Напрягите мышцу с датчиком')
    expect(within(screen.getByTestId('role-eeg')).getByText('Подключение…')).toBeTruthy()
    expect(within(screen.getByTestId('role-eeg')).queryByRole('meter')).toBeNull()
    expect(emgRow.querySelector('[aria-live="polite"]')?.textContent).toBe('Сигнал есть')
  })

  it('tells about lost contact, lost air and errors in words', () => {
    const lost = callibri({ role: 'emg', link: 'connected', contact: false })
    const gone = entry({ role: 'eeg', link: 'lost', in_range: false })
    render(<SensorList sensors={view('scanning', [gone, lost])} roles={DARTS} send={vi.fn()} />)
    expect(within(screen.getByTestId('role-emg')).getByText('Нет контакта')).toBeTruthy()
    expect(within(screen.getByTestId('role-eeg')).getByText('Не в эфире')).toBeTruthy()
  })

  it('shows a hint for an empty role and no hand wording anywhere', () => {
    const { container } = render(<SensorList sensors={view('scanning', [callibri()])} roles={PONG} send={vi.fn()} />)
    expect(screen.getAllByText(/Не выбран: нажмите «Подключить»/)).toHaveLength(2)
    expect(container.textContent?.toLowerCase()).not.toMatch(/рук[аиу]/)
  })

  it('sends unassign for the role', () => {
    const send = vi.fn()
    const emg = callibri({ role: 'emg', link: 'connected', signal: true })
    render(<SensorList sensors={view('scanning', [emg])} roles={DARTS} send={send} />)
    fireEvent.click(within(screen.getByTestId('role-emg')).getByRole('button', { name: 'Отключить' }))
    expect(send).toHaveBeenCalledWith({ action: 'sensors_unassign', value: { role: 'emg' } })
  })

  it('keeps the list after the search stops and offers to search again', () => {
    const send = vi.fn()
    render(<SensorList sensors={view('stopped', [entry({})])} roles={DARTS} send={send} />)
    expect(screen.getByText(/Поиск остановлен/)).toBeTruthy()
    expect(screen.getAllByTestId('sensor-found')).toHaveLength(1)
    fireEvent.click(screen.getByRole('button', { name: 'Искать снова' }))
    expect(send).toHaveBeenCalledWith({ action: 'sensors_scan_start' })
  })

  it('explains what to check when a stopped search found nothing', () => {
    render(<SensorList sensors={view('stopped', [])} roles={DARTS} send={vi.fn()} />)
    expect(screen.getByTestId('sensors-none').textContent).toContain('настройках Bluetooth Windows')
  })

  it('shows a Bluetooth error as an alert and allows another try', () => {
    render(<SensorList sensors={view('error', [], 'Bluetooth выключен')} roles={DARTS} send={vi.fn()} />)
    expect(screen.getByRole('alert').textContent).toBe('Bluetooth выключен')
    expect(screen.getByRole('button', { name: 'Искать снова' })).toBeTruthy()
  })

  it('works with a launcher that does not send the live list yet', () => {
    render(<SensorList sensors={undefined} roles={DARTS} send={vi.fn()} />)
    expect(screen.getByRole('button', { name: 'Искать датчики' })).toBeTruthy()
  })
})

describe('SensorList review fixes', () => {
  it('shows the core error under a failed role and in a failed found row', () => {
    const failed = callibri({ role: 'emg', link: 'failed', error: 'Подключение не завершилось за 20 с' })
    const loose = entry({ link: 'failed', error: 'Датчик занят другой программой' })
    render(<SensorList sensors={view('scanning', [failed, loose])} roles={DARTS} send={vi.fn()} />)
    expect(within(screen.getByTestId('role-emg')).getByText('Ошибка подключения')).toBeTruthy()
    expect(within(screen.getByTestId('role-emg')).getByText('Подключение не завершилось за 20 с')).toBeTruthy()
    expect(within(screen.getByTestId('sensor-found')).getByText('Датчик занят другой программой')).toBeTruthy()
  })

  it('disables the role menu button for a device that is out of the air', () => {
    render(<SensorList sensors={view('scanning', [callibri({ in_range: false, age_s: 30 })])} roles={PONG} send={vi.fn()} />)
    expect((screen.getByRole('button', { name: 'Подключить' }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('moves focus to the role row after assigning from the menu', () => {
    const dev = callibri()
    const props = { roles: PONG, send: vi.fn() }
    const { rerender } = render(<SensorList sensors={view('scanning', [dev])} {...props} />)
    fireEvent.click(screen.getByRole('button', { name: 'Подключить' }))
    fireEvent.click(screen.getAllByRole('menuitem')[1] as HTMLElement)
    rerender(<SensorList sensors={view('scanning', [{ ...dev, role: 'emg_right', link: 'connecting' }])} {...props} />)
    expect(document.activeElement).toBe(within(screen.getByTestId('role-emg_right')).getByRole('button', { name: 'Отключить' }))
  })

  it('shows the auto-stop hint only while scanning', () => {
    const { rerender } = render(<SensorList sensors={view('scanning', [])} roles={DARTS} send={vi.fn()} />)
    expect(screen.getByText(/Поиск остановится через минуту/)).toBeTruthy()
    rerender(<SensorList sensors={view('stopped', [])} roles={DARTS} send={vi.fn()} />)
    expect(screen.queryByText(/Поиск остановится через минуту/)).toBeNull()
  })
})
