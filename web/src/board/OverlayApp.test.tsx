import { act, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, test } from 'vitest'
import { FakeEventSource } from '../test/fakeServer.ts'
import { snapshot } from './fixtures.ts'
import { OverlayApp } from './OverlayApp.tsx'
import { parseScale, parseView } from './overlayParams.ts'
import type { EventSourceLike, Scoreboard } from './useScoreboard.ts'

const createSource = (url: string) => new FakeEventSource(url) as unknown as EventSourceLike

function push(board: Scoreboard) {
  const last = FakeEventSource.instances.at(-1)
  if (!last) throw new Error('поток не открыт')
  act(() => last.emit('scoreboard', board))
}

function renderOverlay(search = '') {
  const root = document.createElement('div')
  root.id = 'root'
  document.body.appendChild(root)
  return render(<OverlayApp createSource={createSource} search={search} />, { container: root })
}

beforeEach(() => {
  FakeEventSource.reset()
})

afterEach(() => {
  document.getElementById('root')?.remove()
  document.documentElement.removeAttribute('style')
  document.body.removeAttribute('style')
})

describe('оверлей OBS', () => {
  test('фон html, body и #root прозрачный, пока оверлей открыт', () => {
    const view = renderOverlay()
    expect(document.documentElement.style.backgroundColor).toBe('transparent')
    expect(document.body.style.backgroundColor).toBe('transparent')
    expect(document.getElementById('root')?.style.backgroundColor).toBe('transparent')
    view.unmount()
    expect(document.body.style.backgroundColor).toBe('')
  })

  test('тот же поток SSE, что у табло', () => {
    renderOverlay()
    expect(FakeEventSource.instances.map((s) => s.url)).toEqual(['/api/v1/scoreboard/stream'])
  })

  test('по умолчанию score: названия, счёт дуэли и суммы по дисциплинам без игроков', () => {
    renderOverlay()
    push(snapshot)
    expect(screen.getByText('Красные')).toBeDefined()
    expect(screen.getByText('Синие')).toBeDefined()
    expect(screen.getByLabelText('Победы команды A').textContent).toBe('2')
    expect(screen.getByLabelText('Победы команды B').textContent).toBe('1')
    const rows = Array.from(document.querySelectorAll('.row'))
    expect(rows.map((r) => r.querySelector('.versus')?.textContent)).toEqual([
      '80vs15',
      '40vs0',
      '10vs20',
    ])
    for (const row of rows) expect(row.querySelector('svg[data-icon]')).not.toBeNull()
    expect(screen.queryByText('Аня')).toBeNull()
    expect(document.querySelectorAll('.player')).toHaveLength(0)
  })

  test('view=full добавляет лучших игроков по дисциплинам, слева A, справа B', () => {
    renderOverlay('?view=full')
    push(snapshot)
    const darts = screen.getByRole('region', { name: 'Дартс' })
    expect(within(darts.querySelector<HTMLElement>('.side-a') as HTMLElement).getByText('Аня')).toBeDefined()
    expect(within(darts.querySelector<HTMLElement>('.side-b') as HTMLElement).getByText('Боря')).toBeDefined()
    expect(screen.getByText('нужно решение')).toBeDefined()
    expect(darts.querySelector('.versus')?.textContent).toBe('80vs15')
  })

  test('обновляется по новому событию', () => {
    renderOverlay()
    push(snapshot)
    push({ teams: snapshot.teams.map((t) => ({ ...t, name: `${t.name}!`, duel_score: 7 })) })
    expect(screen.getByText('Красные!')).toBeDefined()
    expect(screen.getByLabelText('Победы команды A').textContent).toBe('7')
  })

  test('scale задаёт размер через --scale', () => {
    renderOverlay('?scale=1.5')
    push(snapshot)
    expect(screen.getByLabelText('Оверлей табло').style.getPropertyValue('--scale')).toBe('1.5')
  })

  test('без категории и внешних адресов', () => {
    renderOverlay('?view=full')
    push(snapshot)
    const text = document.body.innerHTML.toLowerCase()
    expect(text).not.toContain('овз')
    expect(text).not.toContain('ovz')
    expect(text).not.toContain('general')
    expect(text).not.toMatch(/https?:\/\//)
  })

  test('до первого события ничего не рисует, фон остаётся прозрачным', () => {
    renderOverlay()
    expect(document.querySelectorAll('.plate')).toHaveLength(0)
    expect(document.body.style.backgroundColor).toBe('transparent')
  })
})

describe('параметры оверлея', () => {
  test('view: full или score по умолчанию', () => {
    expect(parseView('?view=full')).toBe('full')
    expect(parseView('?view=score')).toBe('score')
    expect(parseView('?view=что-то')).toBe('score')
    expect(parseView('')).toBe('score')
  })

  test('scale: число в пределах 0.25…4, иначе 1', () => {
    expect(parseScale('?scale=2')).toBe(2)
    expect(parseScale('?scale=0.1')).toBe(0.25)
    expect(parseScale('?scale=99')).toBe(4)
    expect(parseScale('?scale=abc')).toBe(1)
    expect(parseScale('?scale=-3')).toBe(1)
    expect(parseScale('?scale=')).toBe(1)
    expect(parseScale('')).toBe(1)
  })
})
