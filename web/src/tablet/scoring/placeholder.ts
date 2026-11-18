// Заглушка до утверждения методики подсчёта очков (решение 14).
// Единственное место, где бросок или элемент превращается в очки:
// когда методика будет утверждена, меняется только этот файл.

export const THROW_MAX = 60
export const ELEMENT_COUNT = 4
export const ACCURACY_MAX = 100
export const POINTS_MAX = 1000

/** Дартс: очки = сумма бросков. */
export function dartsPoints(throws: readonly number[]): number {
  return throws.reduce((sum, value) => sum + value, 0)
}

/** Футбол (полоса): очки = число выполненных элементов + очки за точность. */
export function footballPoints(elements: readonly boolean[], accuracy: number): number {
  return elements.filter(Boolean).length + accuracy
}

/** Понг: очки игрока вводит волонтёр как есть. */
export function pongPoints(points: number): number {
  return points
}
