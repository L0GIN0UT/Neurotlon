import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, test, vi } from 'vitest'
import { BADGES_URL } from '../staff/api.ts'
import { createFakeServer, json } from '../test/fakeServer.ts'
import type { FakeServer } from '../test/fakeServer.ts'
import { nameSizeMm } from './nameSize.ts'
import { BadgesApp } from './BadgesApp.tsx'
import { QR_MIN_MM, QUIET_MODULES, qrPath, tileSideMm } from './qr.ts'

const SIZE = 21

function matrix(code: string) {
  const rows = Array.from({ length: SIZE }, (_, y) =>
    Array.from({ length: SIZE }, (_, x) => ((x + y) % 2 === 0 ? '1' : '0')).join(''),
  )
  return { code, size: SIZE, rows }
}

interface Seed {
  code: string
  name?: string | null
  photo?: boolean
  here?: boolean
}

function serve(seeds: (string | Seed)[]): FakeServer {
  const rows: Seed[] = seeds.map((seed) => (typeof seed === 'string' ? { code: seed } : seed))
  const server = createFakeServer('admin')
  server.routes.set('GET /participants', () =>
    json(
      rows.map(({ code, name, photo, here }) => ({
        code,
        display_name: name ?? null,
        checked_in: here ?? true,
        checked_in_at: null,
        team: { id: 1, name: 'Красные', color: '#f00' },
        category: 'ovz',
        has_photo: photo ?? false,
        photo_version: photo ? 3 : null,
      })),
    ),
  )
  server.routes.set('GET /participants/qr', () => json(rows.map((r) => matrix(r.code))))
  return server
}

afterEach(() => {
  window.history.replaceState(null, '', '/')
})

describe('страница бейджей', () => {
  test('бейдж: номер и имя на табло есть, команды и категории нет', async () => {
    render(<BadgesApp fetchFn={serve([{ code: 'NT01', name: 'Вера' }, 'NT02', 'NT03']).fetchFn} />)
    expect(await screen.findAllByRole('article')).toHaveLength(3)
    const first = document.querySelector('.id-badge') as HTMLElement
    expect(first.querySelector('.badge-code')?.textContent).toBe('NT01')
    expect(first.querySelector('.badge-name')?.textContent).toBe('Вера')
    expect(document.querySelectorAll('.badge-name')).toHaveLength(1)
    const text = document.querySelector('.badge-list')?.textContent ?? ''
    for (const secret of ['Красные', 'ОВЗ', 'команд', 'категор'])
      expect(text.toLowerCase()).not.toContain(secret.toLowerCase())
    expect(text).toContain('BCI')
    expect(text).toContain('Реальная')
    expect(text).toContain('Партнёры')
  })

  test('длинное имя мельче короткого', () => {
    expect(nameSizeMm('Вера')).toBeGreaterThan(nameSizeMm('Александра-Мария Ив'))
    expect(nameSizeMm('Александра-Мария Иванова-Пе')).toBeLessThanOrEqual(nameSizeMm('Александра-Мария Ив'))
  })

  test('фото подставляется в рамку, без фото силуэт, без имени блока имени нет', async () => {
    render(<BadgesApp fetchFn={serve([{ code: 'NT01', name: 'Вера', photo: true }, 'NT02']).fetchFn} />)
    await screen.findAllByRole('article')
    const [withPhoto, without] = Array.from(document.querySelectorAll<HTMLElement>('.id-badge'))
    const img = withPhoto?.querySelector<HTMLImageElement>('img.photo-img')
    expect(img?.getAttribute('src')).toBe('/api/v1/participants/NT01/photo?v=3')
    expect(without?.querySelector('img.photo-img')).toBeNull()
    expect(without?.querySelector('.silhouette')).not.toBeNull()
    expect(without?.querySelector('.badge-name')).toBeNull()
    expect(without?.querySelector('.has-name')).toBeNull()
  })

  test('печать ждёт загрузки настоящих картинок; ошибка одной не блокирует и не прячет загруженную', async () => {
    const print = vi.spyOn(window, 'print').mockImplementation(() => undefined)
    render(<BadgesApp fetchFn={serve([{ code: 'NT01', photo: true }, { code: 'NT13', photo: true }, 'NT02']).fetchFn} />)
    await screen.findAllByRole('article')
    const button = screen.getByRole('button', { name: 'Печать / Сохранить в PDF' }) as HTMLButtonElement
    const imgOf = (code: string) => screen.getByLabelText(`Бейдж ${code}`).querySelector('img.photo-img')
    // картинки в бейджах запрошены, но не загружены: печать закрыта
    expect(screen.getByText('Загрузка фото… (0 из 2)')).toBeDefined()
    expect(button.disabled).toBe(true)
    fireEvent.load(imgOf('NT01') as Element)
    expect(await screen.findByText('Загрузка фото… (1 из 2)')).toBeDefined()
    expect(button.disabled).toBe(true)
    fireEvent.error(imgOf('NT13') as Element)
    await waitFor(() => expect(button.disabled).toBe(false))
    expect(screen.queryByText(/Загрузка фото/)).toBeNull()
    // сбойное фото: значок вместо картинки
    const failed = screen.getByLabelText('Бейдж NT13')
    expect(failed.querySelector('img.photo-img')).toBeNull()
    expect(failed.querySelector('.photo-fail')?.textContent).toContain('фото')
    // загруженная картинка не пропадает от поздней ошибки
    fireEvent.error(imgOf('NT01') as Element)
    expect(imgOf('NT01')).not.toBeNull()
    expect(screen.getByLabelText('Бейдж NT01').querySelector('.photo-fail')).toBeNull()
    fireEvent.click(button)
    expect(print).toHaveBeenCalled()
    print.mockRestore()
  })

  test('в таблице иконки трёх дисциплин', async () => {
    render(<BadgesApp fetchFn={serve(['NT01']).fetchFn} />)
    const badge = await screen.findByRole('article')
    for (const name of ['darts', 'football', 'pong'])
      expect(badge.querySelector(`svg[data-icon="${name}"]`)).not.toBeNull()
  })

  test('размер листа переключает корневой класс и правило @page', async () => {
    render(<BadgesApp fetchFn={serve(['NT01', 'NT02', 'NT03', 'NT04', 'NT05']).fetchFn} />)
    await screen.findAllByRole('article')
    const root = document.querySelector('.badges-root') as HTMLElement
    const sizes = within(screen.getByRole('group', { name: 'Размер листа' }))
    // по умолчанию лист A4
    expect(root.classList.contains('mode-a4')).toBe(true)
    expect(sizes.getByRole('button', { name: 'A4 по 4' }).getAttribute('aria-pressed')).toBe('true')
    expect(root.querySelector('style')?.textContent).toContain('size: A4')
    // 5 бейджей: два листа A4 (4 + 1)
    expect(root.querySelectorAll('.a4-sheet')).toHaveLength(2)
    expect(root.querySelectorAll('.cut-cell')).toHaveLength(5)
    fireEvent.click(sizes.getByRole('button', { name: 'A3 по 8' }))
    expect(root.classList.contains('mode-a3')).toBe(true)
    expect(root.querySelector('style')?.textContent).toContain('A3 landscape')
    expect(root.querySelectorAll('.a4-sheet')).toHaveLength(1)
    fireEvent.click(sizes.getByRole('button', { name: /Для типографии/ }))
    expect(root.classList.contains('mode-press')).toBe(true)
    expect(root.querySelector('style')?.textContent).toContain('size: 95mm 135mm')
    expect(root.querySelectorAll('.id-badge')).toHaveLength(5)
  })

  test('?codes= предвыбирает коды, счётчик и «Выбрать всех»', async () => {
    window.history.replaceState(null, '', '/badges?codes=nt02,NT03')
    render(<BadgesApp fetchFn={serve(['NT01', 'NT02', 'NT03']).fetchFn} />)
    const badges = await screen.findAllByRole('article')
    expect(badges.map((b) => b.getAttribute('aria-label'))).toEqual(['Бейдж NT02', 'Бейдж NT03'])
    expect(screen.getByText('Выбрано 2 из 3')).toBeDefined()
    const picker = screen.getByRole('group', { name: 'Коды участников' })
    expect((within(picker).getByLabelText(/NT01/) as HTMLInputElement).checked).toBe(false)
    fireEvent.click(within(picker).getByLabelText(/NT01/))
    expect(await screen.findAllByRole('article')).toHaveLength(3)
    fireEvent.click(within(picker).getByLabelText(/NT01/))
    expect(await screen.findAllByRole('article')).toHaveLength(2)
    fireEvent.click(screen.getByRole('button', { name: 'Выбрать всех' }))
    expect(await screen.findAllByRole('article')).toHaveLength(3)
  })

  test('«Только пришедших» и поиск по имени', async () => {
    const seeds = [{ code: 'NT01', name: 'Вера' }, { code: 'NT02', here: false }, { code: 'NT03', name: 'Олег' }]
    render(<BadgesApp fetchFn={serve(seeds).fetchFn} />)
    expect(await screen.findAllByRole('article')).toHaveLength(3)
    fireEvent.click(screen.getByRole('button', { name: 'Только пришедших' }))
    expect(await screen.findAllByRole('article')).toHaveLength(2)
    expect(screen.getByText('Выбрано 2 из 3')).toBeDefined()
    fireEvent.change(screen.getByLabelText('Поиск'), { target: { value: 'оле' } })
    const picker = screen.getByRole('group', { name: 'Коды участников' })
    expect(within(picker).getAllByRole('checkbox')).toHaveLength(1)
  })

  test('тумблер спонсоров убирает и возвращает блок «Партнёры» на каждом бейдже', async () => {
    render(<BadgesApp fetchFn={serve(['NT01', 'NT02']).fetchFn} />)
    await screen.findAllByRole('article')
    const list = document.querySelector('.badge-list') as HTMLElement
    expect(list.querySelectorAll('.partners')).toHaveLength(2)
    expect(list.textContent).toContain('Партнёры')
    fireEvent.click(screen.getByRole('switch', { name: 'Места под спонсоров' }))
    expect(list.querySelectorAll('.partners')).toHaveLength(0)
    expect(list.querySelectorAll('.sponsor-slot')).toHaveLength(0)
    expect(list.textContent).not.toContain('Партнёры')
    fireEvent.click(screen.getByRole('switch', { name: 'Места под спонсоров' }))
    expect(list.querySelectorAll('.sponsor-slot')).toHaveLength(6)
    expect(list.textContent).toContain('Партнёры')
  })

  test('кнопка печати вызывает window.print, ссылки в админку и на простой PDF', async () => {
    const print = vi.spyOn(window, 'print').mockImplementation(() => undefined)
    render(<BadgesApp fetchFn={serve(['NT01']).fetchFn} />)
    await screen.findByRole('article')
    fireEvent.click(screen.getByRole('button', { name: 'Печать / Сохранить в PDF' }))
    expect(print).toHaveBeenCalled()
    expect(screen.getByRole('link', { name: '← Участники' }).getAttribute('href')).toBe('/admin')
    expect(screen.getByText('Как сохранить в PDF')).toBeDefined()
    expect(screen.getByRole('link', { name: 'Простой PDF без фото', hidden: true }).getAttribute('href')).toBe(
      BADGES_URL,
    )
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
