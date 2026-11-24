import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, test, vi } from 'vitest'
import { createFakeServer, json } from '../test/fakeServer.ts'
import { AdminApp } from './AdminApp.tsx'

async function renderShell() {
  const server = createFakeServer('admin')
  server.routes.set('GET /participants', () => json([]))
  render(<AdminApp fetchFn={server.fetchFn} />)
  await screen.findByRole('tab', { name: 'Станции' })
  return screen.getByRole('button', { name: 'Меню' })
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('мобильное меню', () => {
  test('кнопка раскрывает и сворачивает меню', async () => {
    const toggle = await renderShell()
    expect(toggle.getAttribute('aria-expanded')).toBe('false')
    fireEvent.click(toggle)
    expect(toggle.getAttribute('aria-expanded')).toBe('true')
    fireEvent.click(toggle)
    expect(toggle.getAttribute('aria-expanded')).toBe('false')
  })

  test('выбор раздела закрывает меню и возвращает фокус на «Меню»', async () => {
    const toggle = await renderShell()
    fireEvent.click(toggle)
    fireEvent.click(screen.getByRole('tab', { name: 'Станции' }))
    expect(toggle.getAttribute('aria-expanded')).toBe('false')
    expect(document.activeElement).toBe(toggle)
  })

  test('Escape закрывает меню и возвращает фокус на «Меню»', async () => {
    const toggle = await renderShell()
    fireEvent.click(toggle)
    screen.getByRole('tab', { name: 'Станции' }).focus()
    fireEvent.keyDown(screen.getByRole('tab', { name: 'Станции' }), { key: 'Escape' })
    expect(toggle.getAttribute('aria-expanded')).toBe('false')
    expect(document.activeElement).toBe(toggle)
  })

  test('клик вне панели закрывает меню', async () => {
    const toggle = await renderShell()
    fireEvent.click(toggle)
    fireEvent.mouseDown(screen.getByRole('heading', { level: 1 }))
    expect(toggle.getAttribute('aria-expanded')).toBe('false')
  })

  test('клик внутри панели меню не закрывает', async () => {
    const toggle = await renderShell()
    fireEvent.click(toggle)
    fireEvent.mouseDown(screen.getByRole('navigation', { name: 'Страницы' }))
    expect(toggle.getAttribute('aria-expanded')).toBe('true')
  })

  test('расширение окна выше 900 px сбрасывает открытое меню', async () => {
    let listener: ((e: { matches: boolean }) => void) | undefined
    vi.stubGlobal('matchMedia', (query: string) => ({
      matches: false,
      media: query,
      addEventListener: (_: string, fn: (e: { matches: boolean }) => void) => {
        listener = fn
      },
      removeEventListener: () => undefined,
    }))
    const toggle = await renderShell()
    fireEvent.click(toggle)
    expect(toggle.getAttribute('aria-expanded')).toBe('true')
    act(() => listener?.({ matches: true }))
    expect(toggle.getAttribute('aria-expanded')).toBe('false')
  })
})
