import { act, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { FakeEventSource } from '../test/fakeServer.ts'
import { BoardApp } from './BoardApp.tsx'
import { formatPoints, textOn } from './format.ts'
import { retryDelay } from './useScoreboard.ts'
import type { BoardTeam, EventSourceLike, Scoreboard } from './useScoreboard.ts'

const createSource = (url: string) => new FakeEventSource(url) as unknown as EventSourceLike

function team(number: number, name: string, color: string, members: number, total = 0): BoardTeam {
  return {
    rank: number,
    number,
    name,
    color,
    total,
    by_discipline: { darts: total, football: 0, pong: 0 },
    sections_passed: 0,
    finished: false,
    members: Array.from({ length: members }, (_, i) => ({
      label: `NT${String(number * 10 + i).padStart(2, '0')}`,
      total: i,
      sections_passed: i % 7,
      pending: false,
    })),
  }
}

const snapshot: Scoreboard = {
  teams: [
    {
      rank: 1,
      number: 1,
      name: 'Альфа',
      color: '#aa00bb',
      total: 120.5,
      by_discipline: { darts: 80, football: 40.5, pong: 0 },
      sections_passed: 3,
      finished: false,
      members: [
        { label: 'Аня', total: 80, sections_passed: 2, pending: false },
        { label: 'NT02', total: 40.5, sections_passed: 1, pending: true },
      ],
    },
    {
      rank: 2,
      number: 2,
      name: 'Бета',
      color: '#ffd400',
      total: 10,
      by_discipline: { darts: 0, football: 0, pong: 10 },
      sections_passed: 1,
      finished: false,
      members: [{ label: 'Боря', total: 10, sections_passed: 1, pending: false }],
    },
  ],
}

function current(): FakeEventSource {
  const last = FakeEventSource.instances.at(-1)
  if (!last) throw new Error('поток не открыт')
  return last
}

function push(board: Scoreboard) {
  act(() => current().emit('scoreboard', board))
}

beforeEach(() => {
  FakeEventSource.reset()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('табло', () => {
  test('подключается к потоку и ждёт первое событие', () => {
    render(<BoardApp createSource={createSource} />)
    expect(FakeEventSource.instances).toHaveLength(1)
    expect(current().url).toBe('/api/v1/scoreboard/stream')
    expect(screen.getByText('Подключаемся к табло…')).toBeDefined()
  })

  test('рисует команды, места, итоги по дисциплинам и участников', () => {
    render(<BoardApp createSource={createSource} />)
    push(snapshot)

    const alpha = screen.getByRole('region', { name: 'Альфа' })
    expect(within(alpha).getByText('120,5')).toBeDefined()
    expect(within(alpha).getByText('Дартс')).toBeDefined()
    expect(within(alpha).getByText('Футбол')).toBeDefined()
    expect(within(alpha).getByText('Понг')).toBeDefined()
    expect(within(alpha).getByText('40,5', { selector: 'strong' })).toBeDefined()
    expect(within(alpha).getByText('Аня')).toBeDefined()
    expect(within(alpha).getByText('2/6')).toBeDefined()

    const beta = screen.getByRole('region', { name: 'Бета' })
    expect(within(beta).getByText('Боря')).toBeDefined()
    expect(alpha.style.getPropertyValue('--team')).toBe('#aa00bb')
  })

  test('помечает участника, которому нужно решение судьи', () => {
    render(<BoardApp createSource={createSource} />)
    push(snapshot)
    const flags = screen.getAllByText('нужно решение')
    expect(flags).toHaveLength(1)
    expect(flags[0]?.closest('li')?.textContent).toContain('NT02')
  })

  test('обновляется по новому событию', () => {
    render(<BoardApp createSource={createSource} />)
    push(snapshot)
    expect(screen.queryByText('Гамма')).toBeNull()

    push({ teams: [{ ...team(1, 'Гамма', '#00aa11', 1, 300), rank: 1 }] })
    expect(screen.getByRole('region', { name: 'Гамма' })).toBeDefined()
    expect(screen.queryByRole('region', { name: 'Альфа' })).toBeNull()
    expect(screen.getAllByText('300').length).toBeGreaterThan(0)
  })

  test('без жеребьёвки показывает ожидание', () => {
    render(<BoardApp createSource={createSource} />)
    push({ teams: [] })
    expect(screen.getByText('Ждём жеребьёвки')).toBeDefined()
  })

  test('2 команды по 10 участников помещаются целиком', () => {
    render(<BoardApp createSource={createSource} />)
    push({ teams: [team(1, 'Альфа', '#aa00bb', 10), team(2, 'Бета', '#ffd400', 10)] })
    const rows = document.querySelectorAll('.member')
    expect(rows).toHaveLength(20)
    const alpha = screen.getByRole('region', { name: 'Альфа' })
    expect(alpha.style.getPropertyValue('--rows')).toBe('10')
  })

  test('обрыв: показывает предупреждение, данные остаются, браузер переподключается сам', () => {
    render(<BoardApp createSource={createSource} />)
    push(snapshot)
    act(() => current().failReconnecting())
    expect(screen.getByRole('status').textContent).toContain('Нет связи')
    expect(screen.getByRole('region', { name: 'Альфа' })).toBeDefined()
    expect(FakeEventSource.instances).toHaveLength(1)

    push(snapshot)
    expect(screen.queryByRole('status')).toBeNull()
  })

  test('закрытый поток открывается заново с нарастающей паузой', () => {
    vi.useFakeTimers()
    render(<BoardApp createSource={createSource} />)
    push(snapshot)

    act(() => current().failClosed())
    expect(FakeEventSource.instances[0]?.closed).toBe(true)
    expect(FakeEventSource.instances).toHaveLength(1)
    act(() => {
      vi.advanceTimersByTime(999)
    })
    expect(FakeEventSource.instances).toHaveLength(1)
    act(() => {
      vi.advanceTimersByTime(1)
    })
    expect(FakeEventSource.instances).toHaveLength(2)

    // второй сбой подряд: пауза уже 2 с
    act(() => current().failClosed())
    act(() => {
      vi.advanceTimersByTime(1999)
    })
    expect(FakeEventSource.instances).toHaveLength(2)
    act(() => {
      vi.advanceTimersByTime(1)
    })
    expect(FakeEventSource.instances).toHaveLength(3)

    // новый поток доставляет данные, предупреждение исчезает
    push({ teams: [team(1, 'Дельта', '#123456', 2, 5)] })
    expect(screen.getByRole('region', { name: 'Дельта' })).toBeDefined()
    expect(screen.queryByRole('status')).toBeNull()
  })

  test('при закрытии страницы поток закрывается и повторы прекращаются', () => {
    vi.useFakeTimers()
    const view = render(<BoardApp createSource={createSource} />)
    act(() => current().failClosed())
    view.unmount()
    act(() => {
      vi.advanceTimersByTime(60000)
    })
    expect(FakeEventSource.instances).toHaveLength(1)
    expect(current().closed).toBe(true)
  })

  test('мусор в событии игнорируется', () => {
    render(<BoardApp createSource={createSource} />)
    push(snapshot)
    act(() => {
      const source = current()
      source.emit('scoreboard', 'not-a-board')
      source.emit('scoreboard', { nothing: true })
    })
    expect(screen.getByRole('region', { name: 'Альфа' })).toBeDefined()
  })

  test('на табло нет категории: ни «ОВЗ», ни ovz, ни general', () => {
    render(<BoardApp createSource={createSource} />)
    push(snapshot)
    push({ teams: [team(1, 'Альфа', '#aa00bb', 10), team(2, 'Бета', '#ffd400', 10)] })
    for (const text of [document.body.innerHTML, document.body.textContent ?? '']) {
      const lower = text.toLowerCase()
      expect(lower).not.toContain('овз')
      expect(lower).not.toContain('ovz')
      expect(lower).not.toContain('general')
    }
  })

  test('не обращается к внешним адресам', () => {
    render(<BoardApp createSource={createSource} />)
    push(snapshot)
    expect(document.body.innerHTML).not.toMatch(/https?:\/\//)
    expect(FakeEventSource.instances.map((s) => s.url)).toEqual(['/api/v1/scoreboard/stream'])
  })
})

describe('форматирование', () => {
  test('очки по-русски, одна цифра после запятой', () => {
    expect(formatPoints(42.5)).toBe('42,5')
    expect(formatPoints(1000)).toMatch(/^1\s?000$/)
    expect(formatPoints(0)).toBe('0')
  })

  test('цвет текста на цвете команды', () => {
    expect(textOn('#ffd400')).toBe('#111')
    expect(textOn('#1d5fd1')).toBe('#fff')
    expect(textOn('нет')).toBe('#fff')
  })

  test('пауза между повторами растёт до 10 с', () => {
    expect([0, 1, 2, 3, 4, 10].map(retryDelay)).toEqual([1000, 2000, 4000, 8000, 10000, 10000])
  })
})
