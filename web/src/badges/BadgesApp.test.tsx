import { fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, test, vi } from 'vitest'
import { createFakeServer, json } from '../test/fakeServer.ts'
import type { FakeServer } from '../test/fakeServer.ts'
import { BadgesApp } from './BadgesApp.tsx'
import { QR_MIN_MM, QUIET_MODULES, qrPath, tileSideMm } from './qr.ts'

const SIZE = 21

function matrix(code: string) {
  const rows = Array.from({ length: SIZE }, (_, y) =>
    Array.from({ length: SIZE }, (_, x) => ((x + y) % 2 === 0 ? '1' : '0')).join(''),
  )
  return { code, size: SIZE, rows }
}

function serve(codes: string[]): FakeServer {
  const server = createFakeServer('admin')
  server.routes.set('GET /participants', () =>
    json(
      codes.map((code) => ({
        code,
        display_name: 'Секретное имя',
        checked_in: true,
        checked_in_at: null,
        team: { id: 1, name: 'Красные', color: '#f00' },
        category: 'ovz',
      })),
    ),
  )
  server.routes.set('GET /participants/qr', () => json(codes.map(matrix)))
  return server
}

afterEach(() => {
  window.history.replaceState(null, '', '/')
})

describe('страница бейджей', () => {
  test('рисует бейдж на каждого участника без команды, имени и категории', async () => {
    render(<BadgesApp fetchFn={serve(['NT01', 'NT02', 'NT03']).fetchFn} />)
    expect(await screen.findAllByRole('article')).toHaveLength(3)
    const text = document.querySelector('.badge-list')?.textContent ?? ''
    for (const code of ['NT01', 'NT02', 'NT03']) expect(text).toContain(code)
    for (const secret of ['Красные', 'Секретное имя', 'ОВЗ', 'команд', 'категор'])
      expect(text.toLowerCase()).not.toContain(secret.toLowerCase())
    expect(text).toContain('BCI')
    expect(text).toContain('Реальная')
    expect(text).toContain('Партнёры')
  })

  test('в таблице иконки трёх дисциплин', async () => {
    render(<BadgesApp fetchFn={serve(['NT01']).fetchFn} />)
    const badge = await screen.findByRole('article')
    for (const name of ['darts', 'football', 'pong'])
      expect(badge.querySelector(`svg[data-icon="${name}"]`)).not.toBeNull()
  })

  test('режим переключает корневой класс и правило @page', async () => {
    render(<BadgesApp fetchFn={serve(['NT01', 'NT02', 'NT03', 'NT04', 'NT05']).fetchFn} />)
    await screen.findAllByRole('article')
    const root = document.querySelector('.badges-root') as HTMLElement
    // по умолчанию лист A4
    expect(root.classList.contains('mode-a4')).toBe(true)
    expect(root.querySelector('style')?.textContent).toContain('size: A4')
    // 5 бейджей: два листа A4 (4 + 1)
    expect(root.querySelectorAll('.a4-sheet')).toHaveLength(2)
    expect(root.querySelectorAll('.cut-cell')).toHaveLength(5)
    fireEvent.change(screen.getByLabelText('Сколько на листе'), { target: { value: 'a3' } })
    expect(root.classList.contains('mode-a3')).toBe(true)
    expect(root.querySelector('style')?.textContent).toContain('A3 landscape')
    expect(root.querySelectorAll('.a4-sheet')).toHaveLength(1)
    fireEvent.click(screen.getByRole('button', { name: /Для типографии/ }))
    expect(root.classList.contains('mode-press')).toBe(true)
    expect(root.querySelector('style')?.textContent).toContain('size: 95mm 135mm')
    expect(root.querySelectorAll('.id-badge')).toHaveLength(5)
  })

  test('?codes= предвыбирает коды', async () => {
    window.history.replaceState(null, '', '/badges?codes=nt02,NT03')
    render(<BadgesApp fetchFn={serve(['NT01', 'NT02', 'NT03']).fetchFn} />)
    const badges = await screen.findAllByRole('article')
    expect(badges.map((b) => b.getAttribute('aria-label'))).toEqual(['Бейдж NT02', 'Бейдж NT03'])
    const picker = screen.getByRole('group', { name: 'Коды участников' })
    expect((within(picker).getByLabelText('NT01') as HTMLInputElement).checked).toBe(false)
    fireEvent.click(within(picker).getByLabelText('NT01'))
    expect(await screen.findAllByRole('article')).toHaveLength(3)
  })

  test('переключатель спонсоров ставит класс', async () => {
    render(<BadgesApp fetchFn={serve(['NT01']).fetchFn} />)
    await screen.findByRole('article')
    const root = document.querySelector('.badges-root') as HTMLElement
    fireEvent.click(screen.getByLabelText('Показывать места под спонсоров'))
    expect(root.classList.contains('sponsors-off')).toBe(true)
  })

  test('кнопка печати вызывает window.print, ссылка ведёт в админку', async () => {
    const print = vi.spyOn(window, 'print').mockImplementation(() => undefined)
    render(<BadgesApp fetchFn={serve(['NT01']).fetchFn} />)
    await screen.findByRole('article')
    fireEvent.click(screen.getByRole('button', { name: 'Печать / Сохранить в PDF' }))
    expect(print).toHaveBeenCalled()
    expect(screen.getByRole('link', { name: '← Участники' }).getAttribute('href')).toBe('/admin')
    print.mockRestore()
  })

  test('QR-плитка: тёмная часть не меньше 30 мм', async () => {
    render(<BadgesApp fetchFn={serve(['NT01']).fetchFn} />)
    const tile = await screen.findByTestId('qr-tile')
    const side = Number.parseFloat(tile.style.width)
    expect(tile.style.width.endsWith('mm')).toBe(true)
    expect((side * SIZE) / (SIZE + 2 * QUIET_MODULES)).toBeGreaterThanOrEqual(QR_MIN_MM)
    expect(tile.getAttribute('viewBox')).toBe(`0 0 ${SIZE + 8} ${SIZE + 8}`)
  })
})

describe('геометрия QR', () => {
  test.each([21, 25, 29, 33])('плитка для %i модулей даёт ≥30 мм тёмной части', (size) => {
    const side = tileSideMm(size)
    expect((side * size) / (size + 2 * QUIET_MODULES)).toBeGreaterThanOrEqual(QR_MIN_MM)
  })

  test('путь содержит квадрат на каждый тёмный модуль со сдвигом на тихую зону', () => {
    const path = qrPath({ code: 'NT01', size: 2, rows: ['10', '01'] })
    expect(path).toBe('M4 4h1v1h-1zM5 5h1v1h-1z')
  })
})
