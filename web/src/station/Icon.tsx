// Значки интерфейса станции: Tabler Icons 3.52.0 (MIT, лицензия в shared/icons/LICENSE).
// Контуры лежат в репозитории: во время работы внешних файлов нет.

const PATHS = {
  check: ['M5 12l5 5l10 -10'],
  x: ['M18 6l-12 12', 'M6 6l12 12'],
  play: ['M7 4v16l13 -8z'],
  arrow: ['M5 12l14 0', 'M13 18l6 -6', 'M13 6l6 6'],
  back: ['M5 12l14 0', 'M11 18l-6 -6', 'M11 6l-6 6'],
  backspace: [
    'M20 6a1 1 0 0 1 1 1v10a1 1 0 0 1 -1 1h-11l-5 -5a1.5 1.5 0 0 1 0 -2l5 -5z',
    'M12 10l4 4m0 -4l-4 4',
  ],
  warning: [
    'M12 9v4',
    'M10.363 3.591l-8.106 13.534a1.914 1.914 0 0 0 1.636 2.871h16.214a1.914 1.914 0 0 0 1.636 -2.87l-8.106 -13.536a1.914 1.914 0 0 0 -3.274 0z',
    'M12 16h.01',
  ],
  search: ['M3 10a7 7 0 1 0 14 0a7 7 0 1 0 -14 0', 'M21 21l-6 -6'],
  info: ['M3 12a9 9 0 1 0 18 0a9 9 0 1 0 -18 0', 'M12 9h.01', 'M11 12h1v4h1'],
  headband: [
    'M4 13v-1a8 8 0 0 1 16 0v1',
    'M4 13h2a1 1 0 0 1 1 1v3a1 1 0 0 1 -1 1h-1a1 1 0 0 1 -1 -1z',
    'M20 13h-2a1 1 0 0 0 -1 1v3a1 1 0 0 0 1 1h1a1 1 0 0 0 1 -1z',
  ],
  pulse: ['M3 12h4l3 8l4 -16l3 8h4'],
  offline: [
    'M12 18l.01 0',
    'M9.172 15.172a4 4 0 0 1 5.656 0',
    'M6.343 12.343a7.963 7.963 0 0 1 3.864 -2.14m4.163 .155a7.965 7.965 0 0 1 3.287 2',
    'M3.515 9.515a12 12 0 0 1 3.544 -2.455m3.101 -.92a12 12 0 0 1 10.325 3.374',
    'M3 3l18 18',
  ],
} as const

export type IconName = keyof typeof PATHS

export function Icon({ name, className }: { name: IconName; className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill={name === 'play' ? 'currentColor' : 'none'}
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      focusable={false}
    >
      {PATHS[name].map((d) => (
        <path key={d} d={d} />
      ))}
    </svg>
  )
}
