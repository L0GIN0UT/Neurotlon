// Очки за секцию вводит волонтёр как есть: один показатель, а не броски и элементы.
// Физические секции оцениваются по той же шкале, что и BCI: не больше лимита дисциплины
// (`max_points` из /me/config, по умолчанию 10; сервер проверяет его и сам). Понг — исключение:
// там `points` — счёт игры, а очки секции считаются по победам.
// Если методику подсчёта (решение 14) придётся менять, меняется только этот файл.

export const POINTS_MAX = 1000
export const POINTS_STEP = 0.5

/** Верхняя граница очков секции: лимит дисциплины или потолок схемы, если лимит неизвестен. */
export function sectionLimit(maxPoints: number | null | undefined): number {
  return maxPoints ?? POINTS_MAX
}

/** Дартс и футбол: очки за секцию. */
export function sectionPoints(points: number): number {
  return points
}

/** Понг: очки игрока вводит волонтёр как есть. */
export function pongPoints(points: number): number {
  return points
}
