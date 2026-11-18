import { act, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { FakeEventSource } from '../test/fakeServer.ts'
import { BoardApp } from './BoardApp.tsx'
import { rows, snapshot, team } from './fixtures.ts'
import { formatPoints, textOn } from './format.ts'
import { retryDelay } from './useScoreboard.ts'
import type { EventSourceLike, Scoreboard } from './useScoreboard.ts'

const createSource = (url: string) => new FakeEventSource(url) as unknown as EventSourceLike

function current(): FakeEventSource {
  const last = FakeEventSource.instances.at(-1)
  if (!last) throw new Error('поток не открыт')
  return last
}

function push(board: Scoreboard) {
  act(() => current().emit('scoreboard', board))
}

function versus(name: string): string | undefined {
  return screen.getByRole('region', { name }).querySelector('.versus')?.textContent ?? undefined
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

  test('три зоны: шапка со счётом дуэли и три полосы дисциплин по порядку', () => {
    render(<BoardApp createSource={createSource} />)
    push(snapshot)

    const header = screen.getByLabelText('Счёт дуэли')
    expect(within(header).getByText('Красные')).toBeDefined()
    expect(within(header).getByText('Синие')).toBeDefined()
    expect(within(header).getByText('VS')).toBeDefined()

    const bands = Array.from(document.querySelectorAll('.band'))
    expect(bands.map((band) => band.getAttribute('data-discipline'))).toEqual([
      'darts',
      'football',
      'pong',
    ])
    expect(bands.map((band) => band.getAttribute('aria-label'))).toEqual(['Дартс', 'Футбол', 'Понг'])
    for (const band of bands) expect(band.querySelector('svg[data-icon]')).not.toBeNull()
  })

  test('VS в шапке показывает duel_score с сервера, а не очки', () => {
    render(<BoardApp createSource={createSource} />)
    push(snapshot)
    expect(screen.getByLabelText('Победы команды A').textContent).toBe('2')
    expect(screen.getByLabelText('Победы команды B').textContent).toBe('1')
  })

  test('названия и счёт дуэли окрашены в цвет команды', () => {
    render(<BoardApp createSource={createSource} />)
    push(snapshot)
    const header = screen.getByLabelText('Счёт дуэли')
    const red = within(header).getByText('Красные')
    const blue = within(header).getByText('Синие')
    expect(red.style.getPropertyValue('--team')).toBe('#e6194b')
    expect(blue.style.getPropertyValue('--team')).toBe('#4363d8')
  })

  test('в центре полосы — сумма очков команд в дисциплине: A vs B', () => {
    render(<BoardApp createSource={createSource} />)
    push(snapshot)
    expect(versus('Дартс')).toBe('80vs15')
    expect(versus('Футбол')).toBe('40vs0')
    expect(versus('Понг')).toBe('10vs20')
  })

  test('слева игроки A, справа B; у каждого место, имя и очки в этой дисциплине', () => {
    render(<BoardApp createSource={createSource} />)
    push(snapshot)
    const darts = screen.getByRole('region', { name: 'Дартс' })
    const left = darts.querySelector<HTMLElement>('.top.side-a')
    const right = darts.querySelector<HTMLElement>('.top.side-b')
    if (!left || !right) throw new Error('нет списков игроков')
    expect(within(left).getByText('Аня').closest('li')?.textContent).toBe('1Аня80')
    expect(within(right).getByText('Боря').closest('li')?.textContent).toBe('1Боря15')
    expect(within(left).queryByText('Боря')).toBeNull()
    expect(within(screen.getByRole('region', { name: 'Понг' })).getByText('Вера')).toBeDefined()
    expect(within(screen.getByRole('region', { name: 'Футбол' })).queryAllByRole('listitem')).toHaveLength(0)
  })

  test('нет общего списка с итогом: игрок виден только в своих дисциплинах', () => {
    render(<BoardApp createSource={createSource} />)
    push(snapshot)
    expect(screen.getAllByText('Аня')).toHaveLength(1)
    expect(document.querySelectorAll('.members')).toHaveLength(0)
  })

  test('помечает игрока, чья секция в дисциплине в конфликте', () => {
    render(<BoardApp createSource={createSource} />)
    push(snapshot)
    const flags = screen.getAllByText('нужно решение')
    expect(flags).toHaveLength(1)
    expect(flags[0]?.closest('li')?.textContent).toContain('NT02')
  })

  test('игрок в конфликте идёт без номера места', () => {
    render(<BoardApp createSource={createSource} />)
    push(snapshot)
    const pending = screen.getByText('нужно решение').closest('li')
    expect(pending?.querySelector('.place')?.textContent).toBe('')
    expect(pending?.textContent).toBe('NT02нужно решение0')
  })

  test('при трёх и более командах — пометка, что показаны первые две', () => {
    render(<BoardApp createSource={createSource} />)
    push(snapshot)
    expect(screen.queryByText('Табло показывает первые две команды')).toBeNull()
    push({ teams: [...snapshot.teams, team(3, 'Зелёные', '#3cb44b')] })
    expect(screen.getByText('Табло показывает первые две команды')).toBeDefined()
    expect(screen.queryByText('Зелёные')).toBeNull()
  })

  test('обновляется по новому событию', () => {
    render(<BoardApp createSource={createSource} />)
    push(snapshot)
    expect(screen.queryByText('Гамма')).toBeNull()

    push({
      teams: [
        team(1, 'Гамма', '#00aa11', { darts: rows('Г', 1) }, { duel_score: 5, by_discipline: { darts: 300, football: 0, pong: 0 } }),
        team(2, 'Дельта', '#123456'),
      ],
    })
    expect(screen.getByText('Гамма')).toBeDefined()
    expect(screen.queryByText('Красные')).toBeNull()
    expect(screen.getByLabelText('Победы команды A').textContent).toBe('5')
    expect(versus('Дартс')).toBe('300vs0')
  })

  test('без жеребьёвки показывает ожидание', () => {
    render(<BoardApp createSource={createSource} />)
    push({ teams: [] })
    expect(screen.getByText('Ждём жеребьёвки')).toBeDefined()
  })

  test('команды A и B — первые две по номеру, а не по месту', () => {
    render(<BoardApp createSource={createSource} />)
    push({
      teams: [team(2, 'Синие', '#4363d8', {}, { rank: 1 }), team(1, 'Красные', '#e6194b', {}, { rank: 2 })],
    })
    expect(document.querySelector('.name-a')?.textContent).toBe('Красные')
    expect(document.querySelector('.name-b')?.textContent).toBe('Синие')
  })

  test('по 5 игроков на команду в каждой из трёх полос помещаются целиком', () => {
    render(<BoardApp createSource={createSource} />)
    const full = { darts: rows('А', 5), football: rows('Б', 5), pong: rows('В', 5) }
    push({ teams: [team(1, 'Красные', '#e6194b', full), team(2, 'Синие', '#4363d8', full)] })
    expect(document.querySelectorAll('.player')).toHaveLength(30)
    expect(document.querySelectorAll('.band')).toHaveLength(3)
  })

  test('обрыв: показывает предупреждение, данные остаются, браузер переподключается сам', () => {
    render(<BoardApp createSource={createSource} />)
    push(snapshot)
    act(() => current().failReconnecting())
    expect(screen.getByRole('status').textContent).toContain('Нет связи')
    expect(screen.getByText('Красные')).toBeDefined()
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
    push({ teams: [team(1, 'Дельта', '#123456'), team(2, 'Омега', '#654321')] })
    expect(screen.getByText('Дельта')).toBeDefined()
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
    expect(screen.getByText('Красные')).toBeDefined()
  })

  test('на табло нет категории: ни «ОВЗ», ни ovz, ни general', () => {
    render(<BoardApp createSource={createSource} />)
    push(snapshot)
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
    expect(formatPoints(42)).toBe('42')
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
