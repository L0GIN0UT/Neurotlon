import type { Command, StateView } from './types.ts'

/** Ключ экрана: меняется — значит, нужен переход. Ввод цифр экран не меняет. */
export function screenKey(state: StateView): string {
  return state.kind === 'confirm' ? `confirm-${state.candidate.code}` : state.kind
}

/** Что делает клавиша на текущем экране (как на кнопках); null — клавиша не нужна. */
export function commandForKey(state: StateView, key: string): Command | null {
  const enter = key === 'Enter'
  switch (state.kind) {
    case 'idle':
      if (key === 'F2') return { action: 'show_rejected' }
      if (enter) return { action: 'submit_input' }
      if (key === 'Backspace') return { action: 'backspace' }
      if (key === 'Escape') return { action: 'cancel' }
      return /^[0-9A-Za-zА-Яа-яЁё]$/.test(key) ? { action: 'type_char', value: key } : null
    case 'confirm':
      if (enter) return { action: 'confirm' }
      return key === 'Escape' ? { action: 'cancel' } : null
    case 'calibrating':
      if (enter) return (state.stage ? state.stage === 'review' : state.ready) ? { action: 'calibration_continue' } : null
      return key === 'Escape' ? { action: 'back' } : null
    case 'problem':
      return enter ? { action: 'retry' } : null // «Не пройдено» только кнопкой
    case 'rejected':
      if (key === 'Escape') return { action: 'close_rejected' }
      return key === 'e' || key === 'E' ? { action: 'export_rejected' } : null
    default:
      return null
  }
}
