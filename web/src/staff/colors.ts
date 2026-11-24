/** Палитра по умолчанию: те же цвета, что PALETTE в server/src/neurotlon_server/draw.py. */
export const TEAM_PALETTE: readonly string[] = [
  '#E6194B',
  '#4363D8',
  '#3CB44B',
  '#F58231',
  '#911EB4',
  '#42D4F4',
  '#F032E6',
  '#BFEF45',
  '#9A6324',
  '#469990',
  '#800000',
  '#808000',
  '#000075',
  '#E6BEFF',
]

const HEX = /^#[0-9a-fA-F]{6}$/
/** Нормализует ввод («ff8800» или «#FF8800») в «#ff8800»; null, если формат неверный. */
export function parseHex(raw: string): string | null {
  const text = raw.trim()
  const hex = text.startsWith('#') ? text : `#${text}`
  return HEX.test(hex) ? hex.toLowerCase() : null
}

