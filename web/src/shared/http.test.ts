import { describe, expect, test, vi } from 'vitest'
import { createRequester } from './http.ts'

describe('createRequester', () => {
  test('пустое тело при 200 даёт undefined, а не ошибку разбора', async () => {
    const fetchFn = vi.fn(() => Promise.resolve(new Response('', { status: 200 }))) as unknown as typeof fetch
    await expect(createRequester({ fetchFn })('PUT', '/x')).resolves.toBeUndefined()
  })

  test('JSON разбирается как раньше', async () => {
    const fetchFn = vi.fn(() => Promise.resolve(new Response('{"a":1}', { status: 200 }))) as unknown as typeof fetch
    await expect(createRequester({ fetchFn })('GET', '/x')).resolves.toEqual({ a: 1 })
  })
})
