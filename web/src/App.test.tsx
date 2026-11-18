import { render, screen } from '@testing-library/react'
import { expect, test } from 'vitest'
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
