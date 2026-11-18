import type { Discipline, Reason, ResultEntry, ResultSubmission, Section } from './api.ts'
import { POINTS_MAX } from './scoring/placeholder.ts'

export type EntryInput =
  | { code: string; completed: true; points: number }
  | { code: string; completed: false; reason: Reason; comment?: string }

export class PayloadError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'PayloadError'
  }
}

const COMMENT_MAX = 200

/** Правила из shared/openapi.yaml: число участников, wins только у понга, ровно один победитель. */
export function validateEntries(
  discipline: Discipline,
  entries: readonly EntryInput[],
  winner: string | null,
): void {
  const expected = discipline === 'pong' ? 2 : 1
  const codes = new Set(entries.map((e) => e.code))
  if (entries.length !== expected || codes.size !== expected) {
    throw new PayloadError(
      expected === 2 ? 'Для понга нужны два разных игрока' : 'Нужен один участник',
    )
  }
  for (const entry of entries) {
    if (entry.completed) {
      if (!Number.isFinite(entry.points) || entry.points < 0 || entry.points > POINTS_MAX) {
        throw new PayloadError(`Очки должны быть от 0 до ${POINTS_MAX}`)
      }
    } else if ((entry.comment ?? '').trim().length > COMMENT_MAX) {
      throw new PayloadError(`Комментарий не длиннее ${COMMENT_MAX} символов`)
    }
  }
  if (discipline !== 'pong') {
    if (winner !== null) throw new PayloadError('Победитель выбирается только в понге')
    return
  }
  const completed = entries.filter((e) => e.completed)
  if (completed.length === 2) {
    if (winner === null || !codes.has(winner)) throw new PayloadError('Выберите победителя')
  } else if (winner !== null && !completed.some((e) => e.code === winner)) {
    throw new PayloadError('Победителем может быть только завершивший игру')
  }
}

export interface SubmissionInput {
  sessionId: string
  discipline: Discipline
  section: Section
  finishedAt: Date
  entries: readonly EntryInput[]
  /** Только понг: код победителя. */
  winner: string | null
}

export function buildSubmission(input: SubmissionInput): ResultSubmission {
  const { discipline, entries, winner } = input
  validateEntries(discipline, entries, winner)
  const bothCompleted = entries.every((e) => e.completed)
  const body: ResultEntry[] = entries.map((entry) => {
    if (!entry.completed) {
      const comment = entry.comment?.trim()
      return {
        participant_code: entry.code,
        outcome: 'not_completed',
        reason: entry.reason,
        ...(comment ? { comment } : {}),
      }
    }
    const result: ResultEntry = {
      participant_code: entry.code,
      outcome: 'completed',
      points: entry.points,
    }
    if (discipline === 'pong') {
      // Один из двух не завершил: завершивший может передать wins: 1 (без выбора победителя).
      result.wins = bothCompleted ? (entry.code === winner ? 1 : 0) : 1
    }
    return result
  })
  return {
    session_id: input.sessionId,
    discipline,
    section: input.section,
    finished_at: input.finishedAt.toISOString(),
    entries: body,
  }
}
