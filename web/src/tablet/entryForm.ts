import type { Discipline, Reason } from './api.ts'
import { PayloadError, validateEntries } from './payload.ts'
import type { EntryInput } from './payload.ts'
import type { Person } from './people.ts'
import {
  ACCURACY_MAX,
  ELEMENT_COUNT,
  POINTS_MAX,
  dartsPoints,
  footballPoints,
  pongPoints,
} from './scoring/placeholder.ts'

export interface PersonForm {
  completed: boolean
  throws: number[]
  throwInput: string
  elements: boolean[]
  accuracy: string
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
    throws: [],
    throwInput: '',
    elements: Array.from({ length: ELEMENT_COUNT }, () => false),
    accuracy: '',
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

/** Очки участника по форме секции; бросает PayloadError при неверных числах. */
export function formPoints(discipline: Discipline, form: PersonForm): number {
  if (discipline === 'darts') {
    if (form.throws.length === 0) throw new PayloadError('Добавьте хотя бы один бросок')
    return dartsPoints(form.throws)
  }
  if (discipline === 'football') {
    const accuracy = form.accuracy.trim() === '' ? 0 : parseNumber(form.accuracy)
    if (!Number.isInteger(accuracy) || accuracy < 0 || accuracy > ACCURACY_MAX) {
      throw new PayloadError(`Точность — целое число от 0 до ${ACCURACY_MAX}`)
    }
    return footballPoints(form.elements, accuracy)
  }
  const points = parseNumber(form.points)
  if (!Number.isFinite(points) || points < 0 || points > POINTS_MAX) {
    throw new PayloadError(`Очки — число от 0 до ${POINTS_MAX}`)
  }
  return pongPoints(points)
}

export function toEntries(
  discipline: Discipline,
  people: Person[],
  draft: EntryDraft,
): { entries: EntryInput[]; winner: string | null } {
  const entries = people.map((person): EntryInput => {
    const form = draft.forms[person.code] ?? emptyForm()
    if (!form.completed) {
      return { code: person.code, completed: false, reason: form.reason, comment: form.comment }
    }
    return { code: person.code, completed: true, points: formPoints(discipline, form) }
  })
  const bothCompleted = entries.every((e) => e.completed)
  const winner = discipline === 'pong' && bothCompleted ? draft.winner : null
  validateEntries(discipline, entries, winner)
  return { entries, winner }
}

