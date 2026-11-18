import type { ReactElement } from 'react'

// Иконки дисциплин нарисованы здесь же (inline SVG): без внешних файлов и шрифтов.
const COMMON = {
  viewBox: '0 0 64 64',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 3,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
  'aria-hidden': true,
  focusable: false,
} as const

function Darts() {
  return (
    <svg {...COMMON} data-icon="darts">
      <circle cx="30" cy="34" r="22" />
      <circle cx="30" cy="34" r="14" />
      <circle cx="30" cy="34" r="6" fill="currentColor" />
      <path d="M30 34 L54 10" />
      <path d="M54 10 L47 11 M54 10 L53 17" />
    </svg>
  )
}

function Football() {
  return (
    <svg {...COMMON} data-icon="football">
      <path d="M6 54 V16 H58 V54" />
      <path d="M6 28 H58 M6 40 H58 M20 16 V54 M32 16 V54 M44 16 V54" strokeWidth={1.5} />
      <circle cx="32" cy="46" r="8" fill="#0b0f1a" />
      <path d="M32 41 L36 44 L34.5 49 H29.5 L28 44 Z" fill="currentColor" strokeWidth={1.5} />
    </svg>
  )
}

function Pong() {
  return (
    <svg {...COMMON} data-icon="pong">
      <ellipse cx="22" cy="22" rx="14" ry="16" transform="rotate(-30 22 22)" />
      <path d="M31 36 L42 56" strokeWidth={5} />
      <ellipse cx="44" cy="22" rx="14" ry="16" transform="rotate(30 44 22)" opacity={0.55} />
      <circle cx="32" cy="54" r="4" fill="currentColor" />
    </svg>
  )
}

const ICONS: Record<string, () => ReactElement> = { darts: Darts, football: Football, pong: Pong }

export function DisciplineIcon({ discipline }: { discipline: string }) {
  const Icon = ICONS[discipline]
  return Icon ? <Icon /> : null
}
