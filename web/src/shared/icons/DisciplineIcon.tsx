import type { ReactElement } from 'react'

// Иконки дисциплин: Tabler Icons 3.52.0 (MIT, см. LICENSE рядом), контуры без изменений.
// Лежат в репозитории: во время работы системы внешние файлы и шрифты не нужны.
const COMMON = {
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 2,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
  'aria-hidden': true,
  focusable: false,
} as const

// target-arrow
function Darts() {
  return (
    <svg {...COMMON} data-icon="darts">
      <path d="M11 12a1 1 0 1 0 2 0a1 1 0 1 0 -2 0" />
      <path d="M12 7a5 5 0 1 0 5 5" />
      <path d="M13 3.055a9 9 0 1 0 7.941 7.945" />
      <path d="M15 6v3h3l3 -3h-3v-3l-3 3" />
      <path d="M15 9l-3 3" />
    </svg>
  )
}

// ball-football
function Football() {
  return (
    <svg {...COMMON} data-icon="football">
      <path d="M3 12a9 9 0 1 0 18 0a9 9 0 1 0 -18 0" />
      <path d="M12 7l4.76 3.45l-1.76 5.55h-6l-1.76 -5.55l4.76 -3.45" />
      <path d="M12 7v-4m3 13l2.5 3m-.74 -8.55l3.74 -1.45m-11.44 7.05l-2.56 2.95m.74 -8.55l-3.74 -1.45" />
    </svg>
  )
}

// ping-pong
function Pong() {
  return (
    <svg {...COMMON} data-icon="pong">
      <path d="M12.718 20.713a7.64 7.64 0 0 1 -7.48 -12.755l.72 -.72a7.643 7.643 0 0 1 9.105 -1.283l2.387 -2.345a2.08 2.08 0 0 1 3.057 2.815l-.116 .126l-2.346 2.387a7.644 7.644 0 0 1 -1.052 8.864" />
      <path d="M11 18a3 3 0 1 0 6 0a3 3 0 1 0 -6 0" />
      <path d="M9.3 5.3l9.4 9.4" />
    </svg>
  )
}

const ICONS: Record<string, () => ReactElement> = { darts: Darts, football: Football, pong: Pong }

export function DisciplineIcon({ discipline }: { discipline: string }) {
  const Icon = ICONS[discipline]
  return Icon ? <Icon /> : null
}
