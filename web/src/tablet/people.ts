import type { Eligibility } from './api.ts'

export interface Person {
  code: string
  /** null: проверить не удалось (нет связи). */
  info: Eligibility | null
}

export function personLabel(person: Person): string {
  const name = person.info?.display_name
  return name ? `${name} (${person.code})` : person.code
}
