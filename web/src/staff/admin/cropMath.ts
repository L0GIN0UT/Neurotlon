// Математика кадрирования фото в рамку 3:4 (как на бейдже). Чистые функции без DOM.

export interface Size {
  width: number
  height: number
}

export interface Point {
  x: number
  y: number
}

export interface Rect extends Point, Size {}

/** Ширина рамки к высоте. */
export const FRAME_ASPECT = 3 / 4
export const MIN_ZOOM = 1
export const MAX_ZOOM = 3

function limitZoom(zoom: number): number {
  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, zoom))
}

/** Размер видимой части исходного изображения: при масштабе 1× рамка вписана с обрезкой (cover). */
export function cropSize(image: Size, zoom: number): Size {
  const wide = image.width / image.height > FRAME_ASPECT
  const base: Size = wide
    ? { width: image.height * FRAME_ASPECT, height: image.height }
    : { width: image.width, height: image.width / FRAME_ASPECT }
  const z = limitZoom(zoom)
  return { width: base.width / z, height: base.height / z }
}

/** Центр видимой части, не выходящий за границы изображения. */
export function clampCenter(image: Size, zoom: number, center: Point): Point {
  const crop = cropSize(image, zoom)
  const clamp = (value: number, size: number, whole: number) =>
    Math.min(whole - size / 2, Math.max(size / 2, value))
  return {
    x: clamp(center.x, crop.width, image.width),
    y: clamp(center.y, crop.height, image.height),
  }
}

/** Прямоугольник исходного изображения для `drawImage(img, x, y, w, h, ...)`. */
export function cropRect(image: Size, zoom: number, center: Point): Rect {
  const crop = cropSize(image, zoom)
  const c = clampCenter(image, zoom, center)
  return { x: c.x - crop.width / 2, y: c.y - crop.height / 2, ...crop }
}

/** Новый центр после перетаскивания на `delta` экранных пикселей в рамке размером `frame` пикселей. */
export function dragCenter(
  image: Size,
  zoom: number,
  center: Point,
  delta: Point,
  frame: Size,
): Point {
  const crop = cropSize(image, zoom)
  return clampCenter(image, zoom, {
    x: center.x - (delta.x * crop.width) / frame.width,
    y: center.y - (delta.y * crop.height) / frame.height,
  })
}
