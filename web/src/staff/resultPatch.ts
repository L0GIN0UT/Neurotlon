import { DISCIPLINE_NAMES, REASON_TEXTS, SECTION_NAMES } from '../shared/messages.ts'
import type { Reason } from '../shared/types.ts'
import type { ResultPatch, StoredResult } from './api.ts'

export const MAX_CHANGE_REASON = 200

export interface ResultDraft {
  outcome: 'completed' | 'not_completed'
  points: string
  wins: '' | '0' | '1'
  reason: Reason | ''
  comment: string
  changeReason: string
}

export function draftOf(row: StoredResult): ResultDraft {
  return {
    outcome: row.outcome,
    points: row.points === null ? '' : String(row.points),
    wins: row.wins === null ? '' : (String(row.wins) as '0' | '1'),
    reason: row.reason ?? '',
    comment: row.comment ?? '',
    changeReason: '',
  }
}

export type PatchResult = { patch: ResultPatch } | { error: string }

/** Тело PATCH /results/{id}: только изменённые поля и обязательная причина. */
export const POINTS_CEILING = 1000

/** Верхняя граница очков: лимит дисциплины для дартса и футбола, иначе потолок схемы. */
export function pointsLimit(row: StoredResult, maxPoints: number | null | undefined): number {
  return row.discipline === 'pong' ? POINTS_CEILING : (maxPoints ?? POINTS_CEILING)
}

export function buildPatch(
  row: StoredResult,
  draft: ResultDraft,
  maxPoints: number | null = null,
): PatchResult {
  const changeReason = draft.changeReason.trim()
  if (changeReason === '') return { error: 'Укажите причину исправления' }
  if (changeReason.length > MAX_CHANGE_REASON) return { error: 'Причина длиннее 200 символов' }

  const patch: ResultPatch = { change_reason: changeReason }
  let changed = false
  const switched = draft.outcome !== row.outcome
  if (switched) {
    patch.outcome = draft.outcome
    changed = true
  }

  if (draft.outcome === 'completed') {
    const points = Number(draft.points)
    const limit = pointsLimit(row, maxPoints)
    if (draft.points.trim() === '' || !Number.isFinite(points) || points < 0 || points > limit) {
      return { error: `Очки — число от 0 до ${limit}` }
    }
    if (switched || points !== row.points) {
      patch.points = points
      changed = true
    }
    // Победителя можно только назначить: второму игроку сервер сам ставит 0.
    if (row.discipline === 'pong' && draft.wins === '1' && (switched || row.wins !== 1)) {
      patch.wins = 1
      changed = true
    }
  } else {
    if (draft.reason === '') return { error: 'Выберите причину «не пройдено»' }
    if (switched || draft.reason !== row.reason) {
      patch.reason = draft.reason
      changed = true
    }
  }

  const comment = draft.comment.trim()
  if (comment !== (row.comment ?? '')) {
    patch.comment = comment === '' ? null : comment
    changed = true
  }
  return changed ? { patch } : { error: 'Нет изменений' }
}

export function describeResult(row: StoredResult): string {
  const what =
    row.outcome === 'completed'
      ? `очки ${row.points ?? 0}${row.wins === null ? '' : `, побед ${row.wins}`}`
      : `не пройдено (${row.reason ? REASON_TEXTS[row.reason] : '—'})`
  return `${row.participant_code} · ${DISCIPLINE_NAMES[row.discipline]} · ${SECTION_NAMES[row.section]}: ${what}`
}
