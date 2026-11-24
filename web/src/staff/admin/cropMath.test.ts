import { describe, expect, test } from 'vitest'
import { clampCenter, cropRect, cropSize, dragCenter, FRAME_ASPECT, MAX_ZOOM } from './cropMath.ts'

const LANDSCAPE = { width: 4000, height: 3000 }
const PORTRAIT = { width: 600, height: 1200 }

describe('cropSize', () => {
  test('широкое изображение: рамка по высоте', () => {
    expect(cropSize(LANDSCAPE, 1)).toEqual({ width: 2250, height: 3000 })
  })

  test('высокое изображение: рамка по ширине', () => {
    expect(cropSize(PORTRAIT, 1)).toEqual({ width: 600, height: 800 })
  })

  test('сохраняет пропорции 3:4 при любом масштабе', () => {
    for (const zoom of [1, 1.7, 3]) {
      const size = cropSize(LANDSCAPE, zoom)
      expect(size.width / size.height).toBeCloseTo(FRAME_ASPECT)
    }
  })

  test('масштаб ограничен диапазоном 1x-3x', () => {
    expect(cropSize(PORTRAIT, 10)).toEqual(cropSize(PORTRAIT, MAX_ZOOM))
    expect(cropSize(PORTRAIT, 0.2)).toEqual(cropSize(PORTRAIT, 1))
  })
})

describe('cropRect', () => {
  test('по центру изображения', () => {
    expect(cropRect(LANDSCAPE, 1, { x: 2000, y: 1500 })).toEqual({
      x: 875,
      y: 0,
      width: 2250,
      height: 3000,
    })
  })

  test('центр за границами прижимается к краю', () => {
    const rect = cropRect(LANDSCAPE, 2, { x: -500, y: 99999 })
    expect(rect.x).toBe(0)
    expect(rect.y + rect.height).toBe(LANDSCAPE.height)
  })

  test('прямоугольник всегда внутри изображения', () => {
    for (const zoom of [1, 1.5, 3]) {
      for (const center of [
        { x: 0, y: 0 },
        { x: 4000, y: 3000 },
        { x: 2000, y: 1500 },
      ]) {
        const rect = cropRect(LANDSCAPE, zoom, center)
        expect(rect.x).toBeGreaterThanOrEqual(0)
        expect(rect.y).toBeGreaterThanOrEqual(0)
        expect(rect.x + rect.width).toBeLessThanOrEqual(LANDSCAPE.width + 1e-9)
        expect(rect.y + rect.height).toBeLessThanOrEqual(LANDSCAPE.height + 1e-9)
      }
    }
  })
})

describe('clampCenter', () => {
  test('при масштабе 1x по короткой стороне сдвига нет', () => {
    expect(clampCenter(LANDSCAPE, 1, { x: 2000, y: 0 }).y).toBe(1500)
    expect(clampCenter(PORTRAIT, 1, { x: 0, y: 600 }).x).toBe(300)
  })
})

describe('dragCenter', () => {
  const frame = { width: 300, height: 400 }

  test('перетаскивание вправо двигает изображение вправо, центр влево', () => {
    const next = dragCenter(LANDSCAPE, 2, { x: 2000, y: 1500 }, { x: 30, y: 0 }, frame)
    // видимая ширина 1125 источника на 300 px: 30 px = 112.5
    expect(next.x).toBeCloseTo(1887.5)
    expect(next.y).toBe(1500)
  })

  test('сдвиг ограничен рамкой', () => {
    const next = dragCenter(LANDSCAPE, 2, { x: 2000, y: 1500 }, { x: -100000, y: 100000 }, frame)
    const rect = cropRect(LANDSCAPE, 2, next)
    expect(rect.x + rect.width).toBeCloseTo(LANDSCAPE.width)
    expect(rect.y).toBeCloseTo(0)
  })
})
