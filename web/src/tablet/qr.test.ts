import { afterEach, expect, test, vi } from 'vitest'
import { createQrReader } from './qr.ts'

afterEach(() => {
  vi.unstubAllGlobals()
})

function video(width: number): HTMLVideoElement {
  return { videoWidth: width, videoHeight: 10 } as HTMLVideoElement
}

test('uses BarcodeDetector when the browser has it', async () => {
  const detect = vi.fn(() => Promise.resolve([{ rawValue: 'NT07' }]))
  vi.stubGlobal(
    'BarcodeDetector',
    class {
      detect = detect
    },
  )
  const read = createQrReader(document.createElement('canvas'))
  expect(await read(video(100))).toBe('NT07')
  expect(detect).toHaveBeenCalled()
})

test('returns null for an empty frame', async () => {
  const read = createQrReader(document.createElement('canvas'))
  expect(await read(video(0))).toBeNull()
})
