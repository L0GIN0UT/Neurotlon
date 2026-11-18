export type OverlayView = 'score' | 'full'

const MIN_SCALE = 0.25
const MAX_SCALE = 4
/** В компактном виде у каждой команды в строке дисциплины столько лучших игроков. */
export const OVERLAY_TOP = 3

/** `?view=score|full`: всё остальное — `score`. */
export function parseView(search: string): OverlayView {
  return new URLSearchParams(search).get('view') === 'full' ? 'full' : 'score'
}

/** `?scale=1.5`: размер оверлея; неверное значение — 1, крайние — в пределах 0.25…4. */
export function parseScale(search: string): number {
  const raw = new URLSearchParams(search).get('scale')
  const value = raw === null || raw.trim() === '' ? NaN : Number(raw)
  if (!Number.isFinite(value) || value <= 0) return 1
  return Math.min(MAX_SCALE, Math.max(MIN_SCALE, value))
}
