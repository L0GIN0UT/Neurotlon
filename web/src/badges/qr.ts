import type { QrMatrix } from '../staff/api.ts'

/** Минимальная сторона тёмной части QR, мм (shared/participant-code.md). */
export const QR_MIN_MM = 30
/** Свободная «тихая зона» вокруг QR, в модулях. */
export const QUIET_MODULES = 4

/** Сторона белой плитки, мм: тёмная часть (N модулей) не меньше QR_MIN_MM. Округляем вверх до 0,1 мм. */
export function tileSideMm(size: number): number {
  return Math.ceil(((QR_MIN_MM * (size + 2 * QUIET_MODULES)) / size) * 10) / 10
}

/** Один путь из квадратиков для тёмных модулей; координаты в модулях, со сдвигом на тихую зону. */
export function qrPath(matrix: QrMatrix): string {
  const parts: string[] = []
  matrix.rows.forEach((row, y) => {
    for (let x = 0; x < row.length; x += 1) {
      if (row[x] === '1') parts.push(`M${x + QUIET_MODULES} ${y + QUIET_MODULES}h1v1h-1z`)
    }
  })
  return parts.join('')
}
