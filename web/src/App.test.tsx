import { render, screen } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import { FakeEventSource } from './test/fakeServer.ts'
import { App } from './App.tsx'

test('renders title', () => {
  render(<App />)
  expect(screen.getByRole('heading', { name: 'Нейротлон' })).toBeDefined()
})

test('главная ведёт на все страницы', () => {
  render(<App />)
  const links = screen.getAllByRole('link').map((link) => link.getAttribute('href'))
  expect(links).toEqual(['/tablet', '/admin', '/judge', '/board'])
})

test('/overlay открывает оверлей OBS без входа', () => {
  vi.stubGlobal('EventSource', FakeEventSource)
  window.history.pushState({}, '', '/overlay?view=full')
  try {
    const { container } = render(<App />)
    expect(container.querySelector('.overlay')).not.toBeNull()
    expect(screen.queryByRole('heading', { name: 'Нейротлон' })).toBeNull()
  } finally {
    window.history.pushState({}, '', '/')
    vi.unstubAllGlobals()
  }
})
