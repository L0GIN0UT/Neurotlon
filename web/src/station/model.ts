import type { CSSProperties } from 'react'
import type { CandidateView, StateView } from './types.ts'

// У каждой дисциплины свой цвет: им окрашены фон, шаги и акценты.
const ACCENTS: Record<string, string> = {
  darts: '#ff7043',
  football: '#2ecc71',
  pong: '#38bdf8',
}
const DEFAULT_ACCENT = '#5b8cff'

export const accentFor = (discipline: string): string => ACCENTS[discipline] ?? DEFAULT_ACCENT

/** Номер шага в полосе «Бейдж → Проверка → Игра → Результат»; null — полосы нет. */
export function stepOf(kind: StateView['kind']): number | null {
  switch (kind) {
    case 'idle':
    case 'checking':
      return 0
    case 'confirm':
      return 1
    case 'starting':
    case 'playing':
    case 'problem':
      return 2
    case 'done':
      return 3
    default:
      return null
  }
}

export type Hint = readonly [key: string, label: string]

export function hintsFor(state: StateView): readonly Hint[] {
  switch (state.kind) {
    case 'idle':
      return [['Enter', 'Далее'], ['Esc', 'Стереть'], ['F2', 'Отклонённые']]
    case 'confirm':
      return [['Enter', state.is_last ? 'Играть' : 'Дальше'], ['Esc', 'Это не я']]
    case 'problem':
      return [['Enter', 'Повторить']]
    case 'rejected':
      return [['E', 'Экспорт'], ['Esc', 'Назад']]
    case 'blocked':
      return [['Ctrl+Q', 'Выход']]
    default:
      return []
  }
}

export const playerName = (c: CandidateView): string => c.display_name ?? c.code

/** Буква для круга-аватара: инициал имени или цифры кода (`NT07` → `07`). */
export function initials(name: string | null, code: string): string {
  const trimmed = name?.trim()
  if (trimmed) return trimmed.slice(0, 1).toUpperCase()
  const digits = code.replace(/\D/g, '')
  return digits || code.slice(0, 2).toUpperCase()
}

const FALLBACK_TEAM = '#7a869f'
export const teamColor = (c: CandidateView): string => c.team?.color ?? FALLBACK_TEAM

export const accentStyle = (accent: string): CSSProperties => ({ '--accent': accent }) as CSSProperties
