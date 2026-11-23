import type { ReactNode } from 'react'
import { Icon } from './Icon.tsx'
import type { IconName } from './Icon.tsx'

const ICONS: Record<'good' | 'bad' | 'warn' | 'info', IconName> = {
  good: 'check',
  bad: 'warning',
  warn: 'warning',
  info: 'info',
}

/**
 * Сообщение в форме: занимает всю ширину и переносится по словам (плашка-«таблетка» обрезала
 * длинные тексты многоточием).
 */
export function Notice({
  tone,
  children,
  testId,
}: {
  tone: 'good' | 'bad' | 'warn' | 'info'
  children: ReactNode
  testId?: string
}) {
  return (
    <div className={`notice notice-${tone}`} data-testid={testId} role={tone === 'bad' ? 'alert' : 'status'}>
      <Icon name={ICONS[tone]} />
      <div className="notice-text">{children}</div>
    </div>
  )
}
