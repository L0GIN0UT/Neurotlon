import type { Discipline, Reason } from './api.ts'
import { PayloadError, validateEntries } from './payload.ts'
import type { EntryInput } from './payload.ts'
import type { Person } from './people.ts'
import {
  POINTS_MAX,
  POINTS_STEP,
  pongPoints,
  sectionLimit,
  sectionPoints,
} from './scoring/placeholder.ts'

export interface PersonForm {
  completed: boolean
  /** Дартс и футбол: очки за секцию; понг: очки игры. */
  points: string
  reason: Reason
  comment: string
}

export interface EntryDraft {
  forms: Record<string, PersonForm>
  winner: string | null
}

export function emptyForm(): PersonForm {
  return {
    completed: true,
    points: '',
    reason: 'participant_refused',
    comment: '',
  }
}

export function emptyDraft(people: Person[]): EntryDraft {
  return { forms: Object.fromEntries(people.map((p) => [p.code, emptyForm()])), winner: null }
}

export function parseNumber(text: string): number {
  const trimmed = text.trim().replace(',', '.')
  return trimmed === '' ? NaN : Number(trimmed)
}

/** Текст ошибки для очков секции или `null`, если значение подходит (пустое поле — не ошибка). */
export function sectionPointsProblem(text: string, maxPoints: number | null): string | null {
  if (text.trim() === '') return null
  const limit = sectionLimit(maxPoints)
  const value = parseNumber(text)
  const onStep = Math.abs(value / POINTS_STEP - Math.round(value / POINTS_STEP)) < 1e-9
  if (!Number.isFinite(value) || value < 0 || value > limit || !onStep) {
    return `Очки за секцию — число от 0 до ${limit} с шагом 0,5`
  }
  return null
}

/** Новое значение поля после нажатия «+» или «−»: в пределах 0…лимит, с шагом 0,5. */
export function stepPoints(text: string, direction: 1 | -1, maxPoints: number | null): string {
  const current = parseNumber(text)
  const base = Number.isFinite(current) ? current : 0
  const next = Math.min(sectionLimit(maxPoints), Math.max(0, base + direction * POINTS_STEP))
  return String(next)
}

/** Очки участника по форме секции; бросает PayloadError при неверных числах. */
export function formPoints(
  discipline: Discipline,
  form: PersonForm,
  maxPoints: number | null = null,
): number {
  if (discipline === 'pong') {
    const points = parseNumber(form.points)
    if (!Number.isFinite(points) || points < 0 || points > POINTS_MAX) {
      throw new PayloadError(`Очки — число от 0 до ${POINTS_MAX}`)
    }
    return pongPoints(points)
  }
  if (form.points.trim() === '') throw new PayloadError('Введите очки за секцию')
  const problem = sectionPointsProblem(form.points, maxPoints)
  if (problem) throw new PayloadError(problem)
  return sectionPoints(parseNumber(form.points))
}

export function toEntries(
  discipline: Discipline,
  people: Person[],
  draft: EntryDraft,
  maxPoints: number | null = null,
): { entries: EntryInput[]; winner: string | null } {
  const entries = people.map((person): EntryInput => {
    const form = draft.forms[person.code] ?? emptyForm()
    if (!form.completed) {
      return { code: person.code, completed: false, reason: form.reason, comment: form.comment }
    }
    return { code: person.code, completed: true, points: formPoints(discipline, form, maxPoints) }
  })
  const bothCompleted = entries.every((e) => e.completed)
  const winner = discipline === 'pong' && bothCompleted ? draft.winner : null
  validateEntries(discipline, entries, winner, maxPoints)
  return { entries, winner }
}
