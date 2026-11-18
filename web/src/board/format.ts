const numberFormat = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })

export function formatPoints(value: number): string {
  return numberFormat.format(value)
}

/** Чёрный или белый текст поверх цвета команды. */
export function textOn(hex: string): string {
  const match = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex)
  if (!match) return '#fff'
  const [r, g, b] = [match[1], match[2], match[3]].map((part) => parseInt(part ?? '0', 16))
  const luminance = (0.299 * (r ?? 0) + 0.587 * (g ?? 0) + 0.114 * (b ?? 0)) / 255
  return luminance > 0.6 ? '#111' : '#fff'
}
