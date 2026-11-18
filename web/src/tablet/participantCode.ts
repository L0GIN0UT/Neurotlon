// Порт правил из shared/participant-code.md.

const CODE_RE = /^NT(0[1-9]|[1-9][0-9])$/
const INPUT_RE = /^(?:NT)?([0-9]{1,2})$/

/** Приводит ввод или содержимое QR к ID вида NT07; null, если не ID. */
export function normalizeCode(raw: string): string | null {
  const text = raw
    .replace(/[\s\-_]/g, '')
    .toUpperCase()
    .replace(/^Н/, 'N')
    .replace(/^(N)?Т/, '$1T')
  const match = INPUT_RE.exec(text)
  if (!match?.[1]) return null
  const code = `NT${match[1].padStart(2, '0')}`
  return CODE_RE.test(code) ? code : null
}
