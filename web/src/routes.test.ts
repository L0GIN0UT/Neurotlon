import { expect, test } from 'vitest'
import { matches } from './routes.ts'

test('путь совпадает сам и с вложенными, но не с похожим именем', () => {
  expect(matches('/admin', '/admin')).toBe(true)
  expect(matches('/admin/', '/admin')).toBe(true)
  expect(matches('/admin/stations', '/admin')).toBe(true)
  expect(matches('/administrator', '/admin')).toBe(false)
  expect(matches('/', '/admin')).toBe(false)
})
