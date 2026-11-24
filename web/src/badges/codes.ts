/** Коды из `?codes=NT01,NT02` в верхнем регистре, без повторов. */
export function parseCodes(search: string): string[] {
  const raw = new URLSearchParams(search).get('codes') ?? ''
  const codes = raw
    .split(',')
    .map((c) => c.trim().toUpperCase())
    .filter((c) => c !== '')
  return [...new Set(codes)]
}
